"""Graph nodes: the instrumented agent (LLM) node and tool node.

Both nodes record structured trace events (tokens, cost, latency, tool I/O, retries)
into the run's Tracer so the admin dashboard and Loom walkthrough can replay the run.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.agent.context import RunContext
from app.agent.state import AgentState


def build_llm(ctx: RunContext) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": ctx.settings.agent_model,
        "max_tokens": 8000,
        "timeout": 60,
        "max_retries": 2,  # SDK-level retry on 429/5xx
    }
    if ctx.settings.openai_key:
        kwargs["api_key"] = ctx.settings.openai_key
    return ChatOpenAI(**kwargs)


def _split_content(message: AIMessage) -> tuple[str, str | None]:
    """Separate visible text from thinking/reasoning blocks."""
    content = message.content
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype in ("thinking", "reasoning"):
                    reasoning_parts.append(block.get("thinking") or block.get("reasoning") or "")
                elif btype == "redacted_thinking":
                    reasoning_parts.append("[redacted thinking]")
    text = "\n".join(p for p in text_parts if p).strip()
    reasoning = "\n".join(p for p in reasoning_parts if p).strip() or None
    return text, reasoning


def _usage(message: AIMessage) -> tuple[int, int, int, int]:
    """Return (uncached_input, output, cache_read, cache_write) tokens."""
    um = getattr(message, "usage_metadata", None) or {}
    total_input = um.get("input_tokens", 0) or 0
    output = um.get("output_tokens", 0) or 0
    details = um.get("input_token_details", {}) or {}
    cache_read = details.get("cache_read", 0) or 0
    cache_write = details.get("cache_creation", 0) or 0
    uncached_input = max(total_input - cache_read - cache_write, 0)
    return uncached_input, output, cache_read, cache_write


def make_agent_node(ctx: RunContext, llm_with_tools) -> Callable[[AgentState], dict]:
    def agent_node(state: AgentState) -> dict:
        t0 = time.perf_counter()
        ai: AIMessage = llm_with_tools.invoke(state["messages"])
        latency_ms = (time.perf_counter() - t0) * 1000

        text, reasoning = _split_content(ai)
        uncached_input, output, cache_read, cache_write = _usage(ai)
        ctx.tracer.log_llm(
            input_tokens=uncached_input,
            output_tokens=output,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            latency_ms=latency_ms,
            stop_reason=(ai.response_metadata or {}).get("stop_reason")
            or (ai.response_metadata or {}).get("finish_reason"),
            reasoning=reasoning,
            text=text or None,
            tool_calls=[{"name": tc["name"], "args": tc["args"]} for tc in (ai.tool_calls or [])],
        )
        return {"messages": [ai], "iterations": state.get("iterations", 0) + 1}

    return agent_node


def make_tool_node(ctx: RunContext, tools_by_name: dict) -> Callable[[AgentState], dict]:
    def tool_node(state: AgentState) -> dict:
        last = state["messages"][-1]
        tool_messages: list[ToolMessage] = []
        for call in getattr(last, "tool_calls", []) or []:
            name = call["name"]
            args = call.get("args", {}) or {}
            tool = tools_by_name.get(name)
            t0 = time.perf_counter()
            if tool is None:
                latency_ms = (time.perf_counter() - t0) * 1000
                result: Any = {"error": f"Unknown tool '{name}'."}
                ok = False
                error = result["error"]
            else:
                try:
                    result = tool.invoke(args)
                    error = result.get("error") if isinstance(result, dict) else None
                    ok = error is None
                except Exception as exc:  # surface as a tool error → agent can retry
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                    ok = False
                    error = result["error"]
                latency_ms = (time.perf_counter() - t0) * 1000

            ctx.tracer.log_tool(
                name=name,
                tool_input=args,
                output=result,
                latency_ms=latency_ms,
                ok=ok,
                error=error,
            )
            tool_messages.append(
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"], name=name)
            )
        return {"messages": tool_messages}

    return tool_node


def make_should_continue(ctx: RunContext) -> Callable[[AgentState], str]:
    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        has_tool_calls = bool(getattr(last, "tool_calls", None))
        if has_tool_calls and state.get("iterations", 0) < ctx.settings.max_agent_iterations:
            return "tools"
        return "end"

    return should_continue
