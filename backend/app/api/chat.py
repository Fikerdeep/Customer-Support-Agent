"""Chat endpoint — runs one fully-traced agent turn for a customer."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.agent.context import RunContext
from app.agent.graph import build_agent
from app.agent.nodes import _split_content
from app.agent.prompts import build_system_prompt
from app.api.schemas import ChatRequest, ChatResponse
from app.core.config import get_settings
from app.core.observability import Tracer
from app.db.database import get_db
from app.db.models import AgentRun, Customer

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    settings = get_settings()
    if not settings.openai_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured (set `openai_key` in .env).")

    email = req.customer_email.strip().lower()
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"No customer found for email '{req.customer_email}'.")

    session_id = req.session_id or uuid.uuid4().hex
    tracer = Tracer(model=settings.agent_model, session_id=session_id, customer_id=customer.id)
    ctx = RunContext(db=db, auth_customer_id=customer.id, settings=settings, tracer=tracer)

    # System prompt carries the authenticated identity + binding policy.
    system_prompt = build_system_prompt(
        {"name": customer.name, "email": customer.email, "loyalty_tier": customer.loyalty_tier}
    )
    messages: list = [SystemMessage(content=system_prompt)]
    for turn in req.history:
        if turn.role == "user":
            messages.append(HumanMessage(content=turn.content))
        elif turn.role == "assistant":
            messages.append(AIMessage(content=turn.content))
    messages.append(HumanMessage(content=req.message))

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
    reply, _ = _split_content(final) if isinstance(final, AIMessage) else (str(getattr(final, "content", "")), None)
    if not reply:
        reply = "I'm sorry — I couldn't complete that request. Could you rephrase or share your order number?"

    summary = tracer.summary(ctx.decision)
    run = AgentRun(
        session_id=session_id,
        customer_id=customer.id,
        decision=ctx.decision,
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

    return ChatResponse(
        reply=reply,
        decision=ctx.decision,
        run_id=run.id,
        session_id=session_id,
        summary=summary,
    )
