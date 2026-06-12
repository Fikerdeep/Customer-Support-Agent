"""Admin/dashboard data endpoints: customers, orders, run traces, and the
human-in-the-loop escalation queue."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import ResolveEscalationRequest
from app.db.database import get_db
from app.db.models import AgentRun, Customer, Order, Refund

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/customers")
def list_customers(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Customer).order_by(Customer.name).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "loyalty_tier": c.loyalty_tier,
            "lifetime_value": c.lifetime_value,
            "order_count": len(c.orders),
        }
        for c in rows
    ]


@router.get("/customers/{customer_id}/orders")
def customer_orders(customer_id: int, db: Session = Depends(get_db)) -> list[dict]:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    out = []
    for o in customer.orders:
        out.append(
            {
                "order_number": o.order_number,
                "status": o.status,
                "order_date": o.order_date.date().isoformat() if o.order_date else None,
                "delivered_at": o.delivered_at.date().isoformat() if o.delivered_at else None,
                "total_amount": o.total_amount,
                "currency": o.currency,
                "already_refunded": any(r.status == "approved" for r in o.refunds),
                "items": [
                    {
                        "sku": it.sku,
                        "product_name": it.product_name,
                        "category": it.category,
                        "quantity": it.quantity,
                        "unit_price": it.unit_price,
                        "is_final_sale": it.is_final_sale,
                        "is_returnable": it.is_returnable,
                    }
                    for it in o.items
                ],
            }
        )
    return out


@router.get("/runs")
def list_runs(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit).all()
    # map customer ids -> names in one pass
    names = {c.id: c.name for c in db.query(Customer).all()}
    return [
        {
            "id": r.id,
            "session_id": r.session_id,
            "customer_id": r.customer_id,
            "customer_name": names.get(r.customer_id) if r.customer_id is not None else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decision": r.decision,
            "injection_flagged": r.injection_flagged,
            "injection_tags": r.injection_tags.split(",") if r.injection_tags else [],
            "user_message": r.user_message,
            "final_reply": r.final_reply,
            "total_input_tokens": r.total_input_tokens,
            "total_output_tokens": r.total_output_tokens,
            "total_cost_usd": r.total_cost_usd,
            "total_latency_ms": r.total_latency_ms,
            "num_llm_turns": r.num_llm_turns,
            "num_tool_calls": r.num_tool_calls,
            "num_retries": r.num_retries,
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(AgentRun, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    customer = db.get(Customer, r.customer_id) if r.customer_id else None
    try:
        trace = json.loads(r.trace_json or "{}")
    except json.JSONDecodeError:
        trace = {}
    return {
        "id": r.id,
        "session_id": r.session_id,
        "customer_id": r.customer_id,
        "customer_name": customer.name if customer else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "decision": r.decision,
        "user_message": r.user_message,
        "final_reply": r.final_reply,
        "trace": trace,
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    total_runs = db.query(func.count(AgentRun.id)).scalar() or 0
    decision_rows = db.query(AgentRun.decision, func.count(AgentRun.id)).group_by(AgentRun.decision).all()
    by_decision: dict[str, int] = {row[0]: row[1] for row in decision_rows}
    total_cost = db.query(func.coalesce(func.sum(AgentRun.total_cost_usd), 0.0)).scalar() or 0.0
    injection_attempts = (
        db.query(func.count(AgentRun.id)).filter(AgentRun.injection_flagged.is_(True)).scalar() or 0
    )
    pending_escalations = (
        db.query(func.count(Refund.id))
        .filter(Refund.status == "escalated", Refund.resolved_at.is_(None))
        .scalar()
        or 0
    )
    return {
        "total_runs": total_runs,
        "by_decision": by_decision,
        "total_cost_usd": round(float(total_cost), 6),
        "customers": db.query(func.count(Customer.id)).scalar() or 0,
        "orders": db.query(func.count(Order.id)).scalar() or 0,
        "injection_attempts": injection_attempts,
        "pending_escalations": pending_escalations,
    }


@router.get("/escalations")
def list_escalations(db: Session = Depends(get_db)) -> list[dict]:
    """Refunds the agent escalated that still await a human decision."""
    rows = (
        db.query(Refund)
        .filter(Refund.status == "escalated", Refund.resolved_at.is_(None))
        .order_by(Refund.created_at.desc())
        .all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "refund_id": r.id,
                "order_number": r.order.order_number if r.order else None,
                "customer_name": r.order.customer.name if r.order and r.order.customer else None,
                "amount": r.amount,
                "reason": r.reason,
                "policy_rule_applied": r.policy_rule_applied,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


@router.post("/escalations/{refund_id}/resolve")
def resolve_escalation(refund_id: int, body: ResolveEscalationRequest, db: Session = Depends(get_db)) -> dict:
    """Human reviewer approves or denies an escalated refund."""
    refund = db.get(Refund, refund_id)
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")
    if refund.status != "escalated" or refund.resolved_at is not None:
        raise HTTPException(status_code=409, detail="This refund is not awaiting human review.")
    action = body.action.strip().lower()
    if action not in {"approve", "deny"}:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'deny'")

    refund.status = "approved" if action == "approve" else "denied"
    refund.decided_by = "human"
    refund.resolved_at = datetime.now(UTC)
    refund.resolution_note = body.note
    db.commit()
    db.refresh(refund)
    return {
        "refund_id": refund.id,
        "status": refund.status,
        "decided_by": refund.decided_by,
        "resolved_at": refund.resolved_at.isoformat() if refund.resolved_at else None,
        "resolution_note": refund.resolution_note,
    }
