"""Assemble the refund agent's LangGraph state machine.

START → agent ──(tool calls?)──▶ tools ──▶ agent  (loop)
               └──(final answer)──────────▶ END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agent.context import RunContext
from app.agent.nodes import (
    build_llm,
    make_agent_node,
    make_should_continue,
    make_tool_node,
)
from app.agent.state import AgentState
from app.agent.tools import build_tools


def build_agent(ctx: RunContext):
    """Build a compiled graph bound to this request's RunContext."""
    tools = build_tools(ctx)
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = build_llm(ctx).bind_tools(tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent", make_agent_node(ctx, llm_with_tools))  # type: ignore[call-overload]
    graph.add_node("tools", make_tool_node(ctx, tools_by_name))  # type: ignore[call-overload]
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        make_should_continue(ctx),
        {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "agent")
    return graph.compile()
