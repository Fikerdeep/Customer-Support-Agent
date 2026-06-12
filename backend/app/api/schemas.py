"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    customer_email: str
    message: str
    history: list[ChatTurn] = Field(default_factory=list)
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    decision: str
    run_id: int
    session_id: str
    summary: dict[str, Any]
    request_id: str = ""
    injection_flagged: bool = False
    injection_tags: list[str] = Field(default_factory=list)


class ResolveEscalationRequest(BaseModel):
    action: str  # "approve" | "deny"
    note: str = ""
