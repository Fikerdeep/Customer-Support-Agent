"""Seed the SQLite CRM from the LLM-generated ``crm_seed.json``.

Relative ``*_days_ago`` fields are converted to absolute timestamps at seed time so
window-based scenarios remain valid whenever the database is rebuilt. Running this is
idempotent: by default it drops and recreates all tables for a clean, deterministic
state ("works out of the box").
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.core.config import DATA_DIR
from app.db.database import engine, SessionLocal
from app.db.models import Base, Customer, Order, OrderItem, Refund

SEED_FILE = DATA_DIR / "crm_seed.json"


def _days_ago(n: int | None) -> datetime | None:
    if n is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=n)


def seed(reset: bool = True) -> dict[str, int]:
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    data = json.loads(SEED_FILE.read_text())
    counts = {"customers": 0, "orders": 0, "items": 0, "refunds": 0}
    db = SessionLocal()
    try:
        for c in data["customers"]:
            customer = Customer(
                name=c["name"],
                email=c["email"],
                phone=c.get("phone", ""),
                loyalty_tier=c.get("loyalty_tier", "standard"),
                created_at=_days_ago(c.get("created_days_ago", 0)),
                lifetime_value=c.get("lifetime_value", 0.0),
            )
            db.add(customer)
            db.flush()
            counts["customers"] += 1

            for o in c["orders"]:
                items = o["items"]
                total = round(sum(i["unit_price"] * i["quantity"] for i in items), 2)
                order = Order(
                    order_number=o["order_number"],
                    customer_id=customer.id,
                    order_date=_days_ago(o.get("order_days_ago", 0)),
                    delivered_at=_days_ago(o.get("delivered_days_ago")),
                    status=o.get("status", "processing"),
                    total_amount=total,
                    currency=o.get("currency", "USD"),
                )
                db.add(order)
                db.flush()
                counts["orders"] += 1

                for i in items:
                    db.add(
                        OrderItem(
                            order_id=order.id,
                            product_name=i["product_name"],
                            sku=i.get("sku", ""),
                            category=i.get("category", "general"),
                            quantity=i.get("quantity", 1),
                            unit_price=i["unit_price"],
                            is_final_sale=i.get("is_final_sale", False),
                            is_returnable=i.get("is_returnable", True),
                        )
                    )
                    counts["items"] += 1

                if o.get("pre_refunded"):
                    db.add(
                        Refund(
                            order_id=order.id,
                            customer_id=customer.id,
                            amount=total,
                            status="approved",
                            reason="Pre-existing approved refund (seed data).",
                            decided_by="human",
                            policy_rule_applied="eligible",
                            created_at=_days_ago(o.get("delivered_days_ago")) or _days_ago(0),
                        )
                    )
                    counts["refunds"] += 1

        db.commit()
    finally:
        db.close()
    return counts


if __name__ == "__main__":
    result = seed()
    print(f"Seeded database at {engine.url}")
    print(f"  customers={result['customers']} orders={result['orders']} "
          f"items={result['items']} pre_refunds={result['refunds']}")
