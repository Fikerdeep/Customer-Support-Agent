"""Unit tests for the deterministic policy engine (no DB, no LLM)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.policy import Action, PolicyItem, PolicyOrder, evaluate_refund

NOW = datetime.now(UTC)


def item(price, *, final=False, returnable=True, qty=1, item_id=1, category="general"):
    return PolicyItem(item_id, "Product", category, qty, price, final, returnable)


def order(items, *, delivered_days_ago=5, status="delivered", customer_id=1, order_id=1, total=None):
    delivered = NOW - timedelta(days=delivered_days_ago) if delivered_days_ago is not None else None
    total = total if total is not None else round(sum(i.unit_price * i.quantity for i in items), 2)
    return PolicyOrder(order_id, customer_id, status, total, delivered, items)


def evaluate(o, *, auth=1, amount=None, already=False, item_id=None):
    return evaluate_refund(
        o,
        auth_customer_id=auth,
        requested_amount=amount,
        already_refunded=already,
        item_id=item_id,
        return_window_days=30,
        escalation_threshold=500.0,
        now=NOW,
    )


def test_eligible_small_refund_approves():
    d = evaluate(order([item(49.99)]))
    assert d.action is Action.APPROVE
    assert d.rule == "eligible"
    assert d.refundable_amount == 49.99


def test_final_sale_denied():
    d = evaluate(order([item(49.99, final=True)]))
    assert d.action is Action.DENY
    assert d.rule == "final_sale"


def test_non_returnable_denied():
    d = evaluate(order([item(100.0, returnable=False)]))
    assert d.action is Action.DENY
    assert d.rule == "non_returnable"


def test_window_expired_denied():
    d = evaluate(order([item(80.0)], delivered_days_ago=45))
    assert d.action is Action.DENY
    assert d.rule == "window_expired"


def test_window_boundary_29_days_approves():
    d = evaluate(order([item(80.0)], delivered_days_ago=29))
    assert d.action is Action.APPROVE


def test_window_boundary_31_days_denied():
    d = evaluate(order([item(80.0)], delivered_days_ago=31))
    assert d.action is Action.DENY
    assert d.rule == "window_expired"


def test_not_delivered_denied():
    d = evaluate(order([item(320.0)], status="shipped", delivered_days_ago=None))
    assert d.action is Action.DENY
    assert d.rule == "not_delivered"


def test_identity_mismatch_denied():
    d = evaluate(order([item(49.99)], customer_id=1), auth=2)
    assert d.action is Action.DENY
    assert d.rule == "identity_mismatch"


def test_duplicate_refund_denied():
    d = evaluate(order([item(49.99)]), already=True)
    assert d.action is Action.DENY
    assert d.rule == "duplicate_refund"


def test_over_threshold_escalates():
    d = evaluate(order([item(1299.0)]))
    assert d.action is Action.ESCALATE
    assert d.rule == "over_threshold"


def test_exactly_500_approves():
    d = evaluate(order([item(500.0)]))
    assert d.action is Action.APPROVE


def test_just_over_500_escalates():
    d = evaluate(order([item(500.01)]))
    assert d.action is Action.ESCALATE


def test_amount_exceeds_refundable_denied():
    d = evaluate(order([item(50.0)]), amount=100.0)
    assert d.action is Action.DENY
    assert d.rule == "amount_exceeds_refundable"


def test_final_sale_takes_precedence_over_window():
    # A final-sale item that is also outside the window denies on final_sale first.
    d = evaluate(order([item(50.0, final=True)], delivered_days_ago=45))
    assert d.action is Action.DENY
    assert d.rule == "final_sale"


def test_mixed_order_full_refund_denied_but_item_level_approves():
    items = [item(40.0, item_id=10), item(20.0, final=True, item_id=11)]
    full = evaluate(order(items))
    assert full.action is Action.DENY and full.rule == "final_sale"

    single = evaluate(order(items), item_id=10)
    assert single.action is Action.APPROVE
    assert single.refundable_amount == 40.0
