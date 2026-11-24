"""Deterministic business rules. No LLM here on purpose: money decisions must be predictable.

`decide()` is a pure function, so every rule can be unit-tested without a database or a model.
"""
import datetime as dt
from dataclasses import dataclass

from .config import settings


@dataclass
class Decision:
    action: str          # refund | replace | credit | escalate
    amount: float
    reason: str          # internal: shown to staff and in the trace
    public_reason: str   # safe to tell the customer


def _days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds() / 86400


def decide(*, category: str, severity: str, order: dict | None, prior_tickets: int) -> Decision:
    def escalate(reason, public="A member of our team needs to review this personally."):
        return Decision("escalate", 0.0, reason, public)

    # Rule 1: anything safety/legal/fraud related goes to a person.
    if severity == "high":
        return escalate("High-severity language (legal, safety or fraud)")
    # Rule 2: categories the agent has no authority over.
    if category in ("billing", "other"):
        return escalate(f"Category '{category}' is not auto-resolvable")
    # Rule 3: repeat complainers are reviewed by a person.
    if prior_tickets >= settings.repeat_complaint_limit:
        return escalate(f"{prior_tickets} tickets in the last 90 days")
    if order is None:
        return escalate("No matching order")

    # Rule 4: late deliveries -> small goodwill credit while the parcel is still moving.
    if category == "late":
        if order["status"] == "in_transit":
            return Decision("credit", settings.late_credit_amount,
                            "In-transit order past its expected date",
                            "Your order is delayed and we owe you an apology.")
        return escalate(f"Order status is '{order['status']}', not in transit")

    # Rules 5-6: damaged / wrong item need a delivered order, inside the window, under the limit.
    if category in ("damaged", "wrong_item"):
        if order["status"] != "delivered":
            return escalate(f"Order status is '{order['status']}', not delivered")
        age = _days_since(order["delivered_at"])
        if age is not None and age > settings.refund_window_days:
            return escalate(f"Delivered {age:.0f} days ago, outside the {settings.refund_window_days}-day window",
                            "This order is outside our standard window, so a team member will take a look.")
        if order["amount"] > settings.auto_resolve_limit:
            return escalate(f"Amount {order['amount']:.2f} exceeds auto-resolve limit {settings.auto_resolve_limit:.0f}",
                            "Because of the order value, a team member will approve this.")
        if category == "damaged":
            return Decision("refund", order["amount"], "Damaged, in window, under limit", "Refund approved.")
        return Decision("replace", 0.0, "Wrong item, in window, under limit", "Replacement approved.")

    return escalate("No rule matched")
