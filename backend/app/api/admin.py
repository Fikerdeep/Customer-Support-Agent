"""Admin/dashboard data endpoints: customers, their orders, and agent run traces."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AgentRun, Customer, Order

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
            "customer_name": names.get(r.customer_id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decision": r.decision,
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
    by_decision = dict(
        db.query(AgentRun.decision, func.count(AgentRun.id)).group_by(AgentRun.decision).all()
    )
    total_cost = db.query(func.coalesce(func.sum(AgentRun.total_cost_usd), 0.0)).scalar() or 0.0
    return {
        "total_runs": total_runs,
        "by_decision": by_decision,
        "total_cost_usd": round(float(total_cost), 6),
        "customers": db.query(func.count(Customer.id)).scalar() or 0,
        "orders": db.query(func.count(Order.id)).scalar() or 0,
    }
