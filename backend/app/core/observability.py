"""Per-run tracer: captures tool I/O, token usage, cost, latency, and retries.

One :class:`Tracer` is created per ``/api/chat`` run and threaded through the
agent. It produces the structured trace the admin dashboard renders and the Loom
walkthrough narrates.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.pricing import cost_usd

logger = logging.getLogger("loopp.agent")


class Tracer:
    def __init__(self, model: str, session_id: str, customer_id: int | None = None):
        self.model = model
        self.session_id = session_id
        self.customer_id = customer_id
        self.events: list[dict[str, Any]] = []
        self._t0 = time.perf_counter()
        # running totals
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.cost = 0.0
        self.llm_turns = 0
        self.tool_calls = 0
        self.retries = 0

    # -- LLM turns ---------------------------------------------------------
    def log_llm(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        latency_ms: float,
        stop_reason: str | None,
        reasoning: str | None,
        text: str | None,
        tool_calls: list[dict] | None = None,
    ) -> None:
        turn_cost = cost_usd(
            self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.cache_write_tokens += cache_write_tokens
        self.cost = round(self.cost + turn_cost, 6)
        self.llm_turns += 1
        event = {
            "type": "llm",
            "step": len(self.events) + 1,
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "latency_ms": round(latency_ms, 1),
            "cost_usd": turn_cost,
            "stop_reason": stop_reason,
            "reasoning": reasoning,
            "text": text,
            "tool_calls": tool_calls or [],
        }
        self.events.append(event)
        logger.info(
            "llm_turn",
            extra={
                "trace": {k: event[k] for k in ("input_tokens", "output_tokens", "latency_ms", "cost_usd")}
            },
        )

    # -- Tool calls --------------------------------------------------------
    def log_tool(
        self,
        *,
        name: str,
        tool_input: dict,
        output: Any,
        latency_ms: float,
        ok: bool,
        error: str | None = None,
        retry: bool = False,
    ) -> None:
        self.tool_calls += 1
        if retry or not ok:
            self.retries += 1
        event = {
            "type": "tool",
            "step": len(self.events) + 1,
            "name": name,
            "input": tool_input,
            "output": output,
            "latency_ms": round(latency_ms, 1),
            "ok": ok,
            "error": error,
            "is_retry_trigger": (not ok) or retry,
        }
        self.events.append(event)
        logger.info("tool_call name=%s ok=%s latency_ms=%.1f", name, ok, latency_ms)

    # -- Summary -----------------------------------------------------------
    @property
    def total_latency_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)

    def summary(self, decision: str | None = None) -> dict[str, Any]:
        return {
            "model": self.model,
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "decision": decision,
            "total_input_tokens": self.input_tokens,
            "total_output_tokens": self.output_tokens,
            "total_cache_read_tokens": self.cache_read_tokens,
            "total_cache_write_tokens": self.cache_write_tokens,
            "total_cost_usd": self.cost,
            "total_latency_ms": self.total_latency_ms,
            "num_llm_turns": self.llm_turns,
            "num_tool_calls": self.tool_calls,
            "num_retries": self.retries,
        }

    def to_dict(self, decision: str | None = None) -> dict[str, Any]:
        return {"summary": self.summary(decision), "events": self.events}

    def to_json(self, decision: str | None = None) -> str:
        return json.dumps(self.to_dict(decision), default=str)


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "trace"):
            payload["trace"] = record.trace  # type: ignore[attr-defined]
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonLogFormatter())
    root = logging.getLogger("loopp")
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False
