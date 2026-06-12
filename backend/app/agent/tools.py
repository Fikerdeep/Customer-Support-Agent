"""Tool definitions — the agent's only way to touch the world.

Tools are built per request via :func:`build_tools`, closing over the :class:`RunContext`
so the *authenticated* customer identity, DB session, and settings are injected by the
server rather than supplied by the model. ``check_refund_eligibility`` and ``submit_refund``
both route through the deterministic policy engine; ``submit_refund`` re-validates before
writing, so policy is enforced in code regardless of the model's intent.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from app.agent.context import RunContext
from app.agent.prompts import load_policy_text
from app.core.policy import Action, PolicyItem, PolicyOrder, evaluate_refund
from app.db.models import Customer, Order, Refund


def _to_policy_order(order: Order) -> PolicyOrder:
    return PolicyOrder(
        order_id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        total_amount=order.total_amount,
        delivered_at=order.delivered_at,
        items=[
            PolicyItem(
                item_id=it.id,
                product_name=it.product_name,
                category=it.category,
                quantity=it.quantity,
                unit_price=it.unit_price,
                is_final_sale=it.is_final_sale,
                is_returnable=it.is_returnable,
            )
            for it in order.items
        ],
    )


def build_tools(ctx: RunContext) -> list[BaseTool]:
    db = ctx.db
    auth_id = ctx.auth_customer_id

    def _owned_order(order_number: str) -> Order | None:
        """Return the order only if it belongs to the authenticated customer.

        Returning None for both "missing" and "not yours" avoids leaking the existence
        of other customers' orders.
        """
        order = db.query(Order).filter(Order.order_number == order_number.strip()).first()
        if order is None or order.customer_id != auth_id:
            return None
        return order

    def _resolve_item_id(order: Order, item_sku: str | None) -> tuple[int | None, str | None]:
        if not item_sku:
            return None, None
        for it in order.items:
            if it.sku.lower() == item_sku.strip().lower():
                return it.id, None
        return None, f"No item with SKU '{item_sku}' on order {order.order_number}."

    def _already_refunded(order: Order) -> bool:
        return any(r.status == "approved" for r in order.refunds)

    @tool
    def get_account_summary() -> dict:
        """Get the authenticated customer's profile (name, email, loyalty tier, lifetime value).
        Call this if you need to confirm who you are speaking with."""
        c = db.get(Customer, auth_id)
        if not c:
            return {"error": "account not found"}
        return {
            "name": c.name,
            "email": c.email,
            "loyalty_tier": c.loyalty_tier,
            "lifetime_value": c.lifetime_value,
        }

    @tool
    def get_orders() -> dict:
        """List the authenticated customer's orders (order number, status, dates, total,
        item count). Call this when the customer hasn't given an order number or you need
        to see their order history."""
        orders = db.query(Order).filter(Order.customer_id == auth_id).all()
        return {
            "orders": [
                {
                    "order_number": o.order_number,
                    "status": o.status,
                    "order_date": o.order_date.date().isoformat() if o.order_date else None,
                    "delivered_at": o.delivered_at.date().isoformat() if o.delivered_at else None,
                    "total_amount": o.total_amount,
                    "currency": o.currency,
                    "item_count": len(o.items),
                }
                for o in orders
            ]
        }

    @tool
    def get_order_details(order_number: str) -> dict:
        """Get full details for one of the customer's orders, including every item with its
        category, price, and the final-sale / returnable flags, plus whether it has already
        been refunded. Always inspect an order with this before deciding a refund."""
        order = _owned_order(order_number)
        if not order:
            return {"error": f"No order '{order_number}' found on your account."}
        return {
            "order_number": order.order_number,
            "status": order.status,
            "order_date": order.order_date.date().isoformat() if order.order_date else None,
            "delivered_at": order.delivered_at.date().isoformat() if order.delivered_at else None,
            "total_amount": order.total_amount,
            "currency": order.currency,
            "already_refunded": _already_refunded(order),
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
                for it in order.items
            ],
        }

    @tool
    def get_refund_policy() -> dict:
        """Return the full company refund policy text. Use it to ground your reasoning when
        explaining a decision to the customer."""
        return {"policy": load_policy_text()}

    @tool
    def check_refund_eligibility(
        order_number: str, amount: float | None = None, item_sku: str | None = None
    ) -> dict:
        """Advisory check of whether a refund is allowed under policy, WITHOUT issuing it.
        Returns the action (approve / deny / escalate), the specific rule applied, and an
        explanation. Provide `item_sku` to evaluate a single item, or omit it for the whole
        order. Use this to reason about borderline cases before calling submit_refund."""
        order = _owned_order(order_number)
        if not order:
            return {"error": f"No order '{order_number}' found on your account."}
        item_id, err = _resolve_item_id(order, item_sku)
        if err:
            return {"error": err}
        decision = evaluate_refund(
            _to_policy_order(order),
            auth_customer_id=auth_id,
            requested_amount=amount,
            already_refunded=_already_refunded(order),
            item_id=item_id,
            return_window_days=ctx.settings.return_window_days,
            escalation_threshold=ctx.settings.escalation_threshold_usd,
        )
        return decision.to_dict()

    @tool
    def submit_refund(
        order_number: str,
        amount: float | None = None,
        item_sku: str | None = None,
        reason: str = "",
    ) -> dict:
        """Issue the refund decision. This is the system of record: it RE-VALIDATES the
        request against the refund policy before writing anything and will refuse to approve
        a refund the policy forbids — no matter what was discussed. Returns the final action
        (approve / deny / escalate), the rule applied, and the recorded refund id. Call this
        exactly once you have decided to act on a refund."""
        order = _owned_order(order_number)
        if not order:
            return {"error": f"No order '{order_number}' found on your account."}
        item_id, err = _resolve_item_id(order, item_sku)
        if err:
            return {"error": err}

        decision = evaluate_refund(
            _to_policy_order(order),
            auth_customer_id=auth_id,
            requested_amount=amount,
            already_refunded=_already_refunded(order),
            item_id=item_id,
            return_window_days=ctx.settings.return_window_days,
            escalation_threshold=ctx.settings.escalation_threshold_usd,
        )

        status_map = {Action.APPROVE: "approved", Action.DENY: "denied", Action.ESCALATE: "escalated"}
        status = status_map[decision.action]
        refund = Refund(
            order_id=order.id,
            customer_id=auth_id,
            amount=decision.refundable_amount,
            status=status,
            reason=reason or decision.explanation,
            decided_by="agent",
            policy_rule_applied=decision.rule,
        )
        db.add(refund)
        db.commit()
        db.refresh(refund)

        ctx.decision = status
        ctx.decision_rule = decision.rule
        return {
            "action": decision.action.value,
            "rule": decision.rule,
            "explanation": decision.explanation,
            "amount": decision.refundable_amount,
            "currency": order.currency,
            "refund_id": refund.id,
            "order_number": order.order_number,
        }

    @tool
    def escalate_to_human(order_number: str, reason: str) -> dict:
        """Escalate a refund to a human reviewer (e.g. for amounts over the policy limit or
        a genuinely ambiguous case). Records the escalation and returns a ticket reference."""
        order = _owned_order(order_number)
        if not order:
            return {"error": f"No order '{order_number}' found on your account."}
        refund = Refund(
            order_id=order.id,
            customer_id=auth_id,
            amount=order.total_amount,
            status="escalated",
            reason=reason,
            decided_by="agent",
            policy_rule_applied="manual_escalation",
        )
        db.add(refund)
        db.commit()
        db.refresh(refund)
        ctx.decision = "escalated"
        ctx.decision_rule = "manual_escalation"
        return {
            "action": "escalate",
            "ticket_id": f"ESC-{refund.id:05d}",
            "order_number": order.order_number,
            "message": "Escalated to a human reviewer. The customer will be contacted.",
        }

    return [
        get_account_summary,
        get_orders,
        get_order_details,
        get_refund_policy,
        check_refund_eligibility,
        submit_refund,
        escalate_to_human,
    ]
