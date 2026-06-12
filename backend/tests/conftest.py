"""Shared pytest fixtures: a hermetic in-memory DB and a small seeded dataset."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Customer, Order, OrderItem


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded(db):
    """Two customers with a focused set of orders covering the policy branches.

    Returns a dict with the customer objects and order-number constants.
    """
    now = datetime.now(UTC)
    alice = Customer(name="Alice", email="alice@example.com", loyalty_tier="vip")
    bob = Customer(name="Bob", email="bob@example.com", loyalty_tier="standard")
    db.add_all([alice, bob])
    db.flush()

    def make(
        order_number,
        customer,
        price,
        *,
        final=False,
        returnable=True,
        delivered_days=5,
        status="delivered",
        sku="SKU-1",
        category="electronics",
    ):
        delivered = now - timedelta(days=delivered_days) if delivered_days is not None else None
        order = Order(
            order_number=order_number,
            customer_id=customer.id,
            order_date=now - timedelta(days=(delivered_days or 0) + 2),
            delivered_at=delivered,
            status=status,
            total_amount=price,
        )
        db.add(order)
        db.flush()
        db.add(
            OrderItem(
                order_id=order.id,
                product_name="Widget",
                sku=sku,
                category=category,
                quantity=1,
                unit_price=price,
                is_final_sale=final,
                is_returnable=returnable,
            )
        )
        return order

    make("N-1", alice, 49.99)  # normal -> approve
    make("F-1", alice, 129.00, final=True)  # final sale -> deny
    make("G-1", alice, 100.00, returnable=False, category="gift_cards")  # non-returnable -> deny
    make("B-1", alice, 1299.00)  # over threshold -> escalate
    make("W-1", alice, 80.00, delivered_days=45)  # window expired -> deny
    make("S-1", alice, 320.00, status="shipped", delivered_days=None)  # not delivered -> deny
    make("O-1", bob, 50.00)  # belongs to Bob -> identity guard
    db.commit()

    return {"alice": alice, "bob": bob}
