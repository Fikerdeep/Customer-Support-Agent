"""Per-request run context shared by the graph nodes and tools.

Carries the DB session, the *authenticated* customer id (injected by the server,
never supplied by the model), settings, the tracer, and the resolved decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.observability import Tracer


@dataclass
class RunContext:
    db: Session
    auth_customer_id: int
    settings: Settings
    tracer: Tracer
    decision: str = "pending"  # pending|approved|denied|escalated
    decision_rule: str | None = None
