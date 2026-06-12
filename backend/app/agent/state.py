"""LangGraph state for the refund agent."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # Conversation, merged by the add_messages reducer (preserves tool + thinking blocks).
    messages: Annotated[list, add_messages]
    # Loop guard incremented on every agent turn.
    iterations: int
