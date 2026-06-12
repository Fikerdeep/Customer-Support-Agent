"""Streaming variant of the agent loop for the SSE endpoint.

Reuses the exact same tools, policy enforcement, and tracer as the graph — only the
control flow is unrolled here so we can emit token deltas and live tool-call status as
Server-Sent Events. The non-streaming graph remains the path used by the API/eval/tests
(where precise token accounting matters most).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import ToolMessage

from app.agent.context import RunContext
from app.agent.nodes import _split_content, _usage, build_llm
from app.agent.tools import build_tools


async def stream_agent(ctx: RunContext, messages: list) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield (event_type, payload) tuples: token | tool_start | tool_result | final."""
    tools = build_tools(ctx)
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = build_llm(ctx).bind_tools(tools)

    convo = list(messages)
    final_reply = ""

    for _ in range(ctx.settings.max_agent_iterations):
        t0 = time.perf_counter()
        gathered: Any = None
        async for chunk in llm_with_tools.astream(convo):
            gathered = chunk if gathered is None else gathered + chunk
            piece = chunk.content
            if isinstance(piece, str) and piece:
                yield "token", {"text": piece}
        latency_ms = (time.perf_counter() - t0) * 1000

        ai = gathered
        if ai is None:
            break
        convo = convo + [ai]

        text, reasoning = _split_content(ai)
        uncached_in, out_tok, cache_r, cache_w = _usage(ai)
        ctx.tracer.log_llm(
            input_tokens=uncached_in,
            output_tokens=out_tok,
            cache_read_tokens=cache_r,
            cache_write_tokens=cache_w,
            latency_ms=latency_ms,
            stop_reason=(ai.response_metadata or {}).get("finish_reason"),
            reasoning=reasoning,
            text=text or None,
            tool_calls=[{"name": tc["name"], "args": tc["args"]} for tc in (ai.tool_calls or [])],
        )

        if not getattr(ai, "tool_calls", None):
            final_reply = text
            break

        for tc in ai.tool_calls:
            yield "tool_start", {"name": tc["name"], "input": tc["args"]}
            tt0 = time.perf_counter()
            tool = tools_by_name.get(tc["name"])
            if tool is None:
                result: Any = {"error": f"Unknown tool '{tc['name']}'."}
                ok, err = False, result["error"]
            else:
                try:
                    result = tool.invoke(tc["args"])
                    err = result.get("error") if isinstance(result, dict) else None
                    ok = err is None
                except Exception as exc:
                    result, ok, err = {"error": f"{type(exc).__name__}: {exc}"}, False, None
                    err = result["error"]
            ctx.tracer.log_tool(
                name=tc["name"],
                tool_input=tc["args"],
                output=result,
                latency_ms=(time.perf_counter() - tt0) * 1000,
                ok=ok,
                error=err,
            )
            yield "tool_result", {"name": tc["name"], "ok": ok, "output": result}
            convo = convo + [
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=tc["id"], name=tc["name"])
            ]

    if not final_reply:
        final_reply = (
            "I'm sorry — I couldn't complete that request. Could you rephrase or share your order number?"
        )
    yield "final", {"reply": final_reply}
