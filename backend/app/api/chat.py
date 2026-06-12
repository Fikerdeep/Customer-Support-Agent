"""Chat endpoint — runs one fully-traced agent turn for a customer.

Edge concerns layered here: idempotency (retries don't re-run the agent or double-refund),
per-IP rate limiting, a prompt-injection guardrail (observe + flag), and request-id propagation.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.agent.context import RunContext
from app.agent.graph import build_agent
from app.agent.nodes import _split_content
from app.agent.prompts import build_system_prompt
from app.agent.streaming import stream_agent
from app.api.schemas import ChatRequest, ChatResponse
from app.core.config import get_settings
from app.core.observability import Tracer
from app.core.security import chat_rate_limiter, detect_injection
from app.db.database import get_db
from app.db.models import AgentRun, Customer, IdempotencyKey

router = APIRouter(prefix="/api", tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _build_messages(customer, history, message) -> list:
    msgs: list = [
        SystemMessage(
            content=build_system_prompt(
                {"name": customer.name, "email": customer.email, "loyalty_tier": customer.loyalty_tier}
            )
        )
    ]
    for turn in history:
        if turn.role == "user":
            msgs.append(HumanMessage(content=turn.content))
        elif turn.role == "assistant":
            msgs.append(AIMessage(content=turn.content))
    msgs.append(HumanMessage(content=message))
    return msgs


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)) -> ChatResponse:
    settings = get_settings()
    if not settings.openai_key:
        raise HTTPException(
            status_code=500, detail="OpenAI API key not configured (set `openai_key` in .env)."
        )

    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)

    # Idempotency: replay a cached response for a repeated Idempotency-Key.
    idem_key = request.headers.get("Idempotency-Key")
    if idem_key:
        cached = db.get(IdempotencyKey, idem_key)
        if cached:
            return ChatResponse(**json.loads(cached.response_json))

    # Per-IP rate limit.
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = chat_rate_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please slow down and try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )

    email = req.customer_email.strip().lower()
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"No customer found for email '{req.customer_email}'.")

    # Input guardrail (observe-only): flag likely injection / social-engineering.
    injection_flagged, injection_tags = detect_injection(req.message)

    session_id = req.session_id or uuid.uuid4().hex
    tracer = Tracer(model=settings.agent_model, session_id=session_id, customer_id=customer.id)
    ctx = RunContext(db=db, auth_customer_id=customer.id, settings=settings, tracer=tracer)

    messages = _build_messages(customer, req.history, req.message)

    agent = build_agent(ctx)
    recursion_limit = settings.max_agent_iterations * 2 + 4
    try:
        result = agent.invoke(
            {"messages": messages, "iterations": 0},
            config={"recursion_limit": recursion_limit},
        )
    except Exception as exc:  # surface model/tool failures cleanly to the UI
        raise HTTPException(status_code=502, detail=f"Agent run failed: {type(exc).__name__}: {exc}") from exc

    final = result["messages"][-1]
    reply, _ = (
        _split_content(final) if isinstance(final, AIMessage) else (str(getattr(final, "content", "")), None)
    )
    if not reply:
        reply = "I'm sorry — I couldn't complete that request. Could you rephrase or share your order number?"

    summary = tracer.summary(ctx.decision)
    run = AgentRun(
        session_id=session_id,
        customer_id=customer.id,
        decision=ctx.decision,
        request_id=request_id,
        injection_flagged=injection_flagged,
        injection_tags=",".join(injection_tags),
        user_message=req.message,
        final_reply=reply,
        total_input_tokens=summary["total_input_tokens"],
        total_output_tokens=summary["total_output_tokens"],
        total_cost_usd=summary["total_cost_usd"],
        total_latency_ms=summary["total_latency_ms"],
        num_llm_turns=summary["num_llm_turns"],
        num_tool_calls=summary["num_tool_calls"],
        num_retries=summary["num_retries"],
        trace_json=tracer.to_json(ctx.decision),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    response = ChatResponse(
        reply=reply,
        decision=ctx.decision,
        run_id=run.id,
        session_id=session_id,
        request_id=request_id,
        injection_flagged=injection_flagged,
        injection_tags=injection_tags,
        summary=summary,
    )

    if idem_key:
        db.add(IdempotencyKey(key=idem_key, response_json=response.model_dump_json()))
        db.commit()

    return response


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    """Server-Sent Events: streams token deltas + live tool-call status, then a final event.

    Events: `start`, `token` {text}, `tool_start` {name,input}, `tool_result` {name,ok,output},
    `done` {decision,run_id,summary}, `error` {message}.
    """
    settings = get_settings()
    if not settings.openai_key:
        raise HTTPException(
            status_code=500, detail="OpenAI API key not configured (set `openai_key` in .env)."
        )

    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = chat_rate_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429, detail="Rate limit exceeded.", headers={"Retry-After": str(retry_after)}
        )

    email = req.customer_email.strip().lower()
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"No customer found for email '{req.customer_email}'.")

    injection_flagged, injection_tags = detect_injection(req.message)
    session_id = req.session_id or uuid.uuid4().hex
    tracer = Tracer(model=settings.agent_model, session_id=session_id, customer_id=customer.id)
    ctx = RunContext(db=db, auth_customer_id=customer.id, settings=settings, tracer=tracer)
    messages = _build_messages(customer, req.history, req.message)

    async def event_stream():
        yield _sse(
            "start",
            {
                "session_id": session_id,
                "request_id": request_id,
                "injection_flagged": injection_flagged,
                "injection_tags": injection_tags,
            },
        )
        final_reply = ""
        try:
            async for etype, data in stream_agent(ctx, messages):
                if etype == "final":
                    final_reply = data["reply"]
                else:
                    yield _sse(etype, data)

            summary = tracer.summary(ctx.decision)
            run = AgentRun(
                session_id=session_id,
                customer_id=customer.id,
                decision=ctx.decision,
                request_id=request_id,
                injection_flagged=injection_flagged,
                injection_tags=",".join(injection_tags),
                user_message=req.message,
                final_reply=final_reply,
                total_input_tokens=summary["total_input_tokens"],
                total_output_tokens=summary["total_output_tokens"],
                total_cost_usd=summary["total_cost_usd"],
                total_latency_ms=summary["total_latency_ms"],
                num_llm_turns=summary["num_llm_turns"],
                num_tool_calls=summary["num_tool_calls"],
                num_retries=summary["num_retries"],
                trace_json=tracer.to_json(ctx.decision),
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            yield _sse(
                "done",
                {
                    "decision": ctx.decision,
                    "run_id": run.id,
                    "session_id": session_id,
                    "request_id": request_id,
                    "injection_flagged": injection_flagged,
                    "summary": summary,
                },
            )
        except Exception as exc:
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": request_id},
    )
