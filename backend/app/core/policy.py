"""Deterministic refund policy engine — the real source of truth.

This module is intentionally free of any LLM, network, or ORM dependency: it is a
pure function over plain facts. Both ``check_refund_eligibility`` (advisory) and
``submit_refund`` (the write path) route through :func:`evaluate_refund`, so the
policy is enforced in code regardless of what the model is argued into saying.

Rules (mirrors ``app/data/refund_policy.md``), evaluated in order:
  1. Identity      — the order must belong to the authenticated requester.
  2. Duplicate     — an order with an existing approved refund cannot be refunded again.
  3. Final sale    — final-sale items are never refundable.
  4. Returnable    — non-returnable categories (gift cards, perishables, …) are never refundable.
  5. Delivery      — only delivered orders are refundable.
  6. Window        — must be within ``return_window_days`` of delivery.
  7. Amount        — the request cannot exceed the refundable amount.
  8. Threshold     — otherwise-eligible refunds over ``escalation_threshold`` go to a human.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class Action(StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"


@dataclass
class PolicyItem:
    item_id: int
    product_name: str
    category: str
    quantity: int
    unit_price: float
    is_final_sale: bool
    is_returnable: bool

    @property
    def subtotal(self) -> float:
        return round(self.unit_price * self.quantity, 2)


@dataclass
class PolicyOrder:
    order_id: int
    customer_id: int
    status: str
    total_amount: float
    delivered_at: datetime | None
    items: list[PolicyItem]


@dataclass
class PolicyDecision:
    action: Action
    rule: str
    explanation: str
    refundable_amount: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "rule": self.rule,
            "explanation": self.explanation,
            "refundable_amount": self.refundable_amount,
        }


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def evaluate_refund(
    order: PolicyOrder,
    auth_customer_id: int,
    requested_amount: float | None,
    already_refunded: bool,
    *,
    item_id: int | None = None,
    return_window_days: int = 30,
    escalation_threshold: float = 500.0,
    now: datetime | None = None,
) -> PolicyDecision:
    """Evaluate a refund request and return the binding decision."""
    now = _aware(now or datetime.now(UTC))

    # 1. Identity — must own the order.
    if order.customer_id != auth_customer_id:
        return PolicyDecision(
            Action.DENY,
            "identity_mismatch",
            "This order is not associated with the authenticated account, so no refund can be issued.",
        )

    # 2. Duplicate — already refunded.
    if already_refunded:
        return PolicyDecision(
            Action.DENY,
            "duplicate_refund",
            "A refund has already been approved for this order; duplicate refunds are not permitted.",
        )

    # Resolve target items (whole order, or a single item).
    if item_id is not None:
        targets = [i for i in order.items if i.item_id == item_id]
        if not targets:
            return PolicyDecision(
                Action.DENY,
                "item_not_found",
                f"No item with id {item_id} exists on order {order.order_id}.",
            )
    else:
        targets = order.items

    # 3. Final sale.
    final_sale = [i for i in targets if i.is_final_sale]
    if final_sale:
        names = ", ".join(i.product_name for i in final_sale)
        return PolicyDecision(
            Action.DENY,
            "final_sale",
            f"Final-sale items cannot be refunded under any circumstances: {names}.",
        )

    # 4. Non-returnable category.
    non_returnable = [i for i in targets if not i.is_returnable]
    if non_returnable:
        names = ", ".join(f"{i.product_name} ({i.category})" for i in non_returnable)
        return PolicyDecision(
            Action.DENY,
            "non_returnable",
            f"These items belong to non-returnable categories: {names}.",
        )

    # 5. Delivery.
    if order.delivered_at is None or order.status not in {"delivered", "cancelled"}:
        return PolicyDecision(
            Action.DENY,
            "not_delivered",
            "Only delivered orders are eligible for a refund; this order has not been delivered.",
        )

    # 6. Return window.
    delivered = _aware(order.delivered_at)
    age_days = (now - delivered).days
    if now - delivered > timedelta(days=return_window_days):
        return PolicyDecision(
            Action.DENY,
            "window_expired",
            f"The {return_window_days}-day return window has passed (delivered {age_days} days ago).",
        )

    # 7. Amount sanity.
    refundable = (
        round(sum(i.subtotal for i in targets), 2) if item_id is not None else round(order.total_amount, 2)
    )
    amount = requested_amount if requested_amount and requested_amount > 0 else refundable
    if amount > refundable + 0.001:
        return PolicyDecision(
            Action.DENY,
            "amount_exceeds_refundable",
            f"Requested ${amount:.2f} exceeds the refundable amount of ${refundable:.2f}.",
        )

    # 8. Escalation threshold.
    if amount > escalation_threshold:
        return PolicyDecision(
            Action.ESCALATE,
            "over_threshold",
            f"Refund of ${amount:.2f} exceeds the ${escalation_threshold:.0f} auto-approval limit and "
            "requires human escalation.",
            refundable_amount=amount,
        )

    # Eligible.
    return PolicyDecision(
        Action.APPROVE,
        "eligible",
        f"Refund of ${amount:.2f} meets all policy requirements and is approved.",
        refundable_amount=amount,
    )
