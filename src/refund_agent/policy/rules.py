"""Refund eligibility rules: the single source of truth.

The agent can only *report* what `decide_refund` returns; it can never widen
eligibility. The module is pure (no I/O, no clock) so every rule is trivially
testable and deterministic: "today" is always passed in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from refund_agent.config import Settings
from refund_agent.policy.models import (
    DeclineReason,
    ItemDecision,
    Purchase,
    RefundDecision,
    Ticket,
    TicketStatus,
)

_ACTIVE_STATUSES = frozenset({TicketStatus.APPROVED, TicketStatus.PENDING_REVIEW})


@dataclass(frozen=True)
class PolicySettings:
    """The tunable numbers the rules need, decoupled from env loading."""

    window_days: int
    review_threshold_cents: int
    running_total_days: int

    @classmethod
    def from_settings(cls, s: Settings) -> "PolicySettings":
        """Project the app-wide settings onto the subset the rules use."""
        return cls(
            window_days=s.refund_window_days,
            review_threshold_cents=s.review_threshold_cents,
            running_total_days=s.running_total_days,
        )


def _dedupe(ids: Sequence[UUID]) -> list[UUID]:
    """Drop repeats, keeping first occurrence, so an item is never paid twice."""
    return list(dict.fromkeys(ids))


def _ids_on(tickets: Sequence[Ticket], status: TicketStatus) -> set[UUID]:
    return {pid for t in tickets if t.status is status for pid in t.purchase_ids}


def _judge(
    purchase: Purchase | None,
    today: date,
    settings: PolicySettings,
    rejected: set[UUID],
    active: set[UUID],
) -> DeclineReason | None:
    """Return the first matching decline reason, or None if eligible.

    Order matters: ownership first (never leak info about others' purchases),
    then ticket history, then date rules.
    """
    if purchase is None:
        return DeclineReason.NOT_OWNED
    if purchase.id in rejected:
        return DeclineReason.PREVIOUSLY_REJECTED
    if purchase.id in active:
        return DeclineReason.ALREADY_REFUNDED
    age_days = (today - purchase.purchased_on).days
    if age_days < 0:
        return DeclineReason.FUTURE_DATE
    if age_days > settings.window_days:
        return DeclineReason.OUTSIDE_WINDOW
    return None


def _prior_total(tickets: Sequence[Ticket], today: date, days: int) -> int:
    """Sum of recent approved/pending refunds, so splitting requests can't dodge review."""
    return sum(
        t.amount_cents
        for t in tickets
        if t.status in _ACTIVE_STATUSES and 0 <= (today - t.created_at.date()).days <= days
    )


def decide_refund(
    purchases: Sequence[Purchase],
    requested_ids: Sequence[UUID],
    existing_tickets: Sequence[Ticket],
    today: date,
    settings: PolicySettings,
) -> RefundDecision:
    """Decide which requested purchases are refundable and the ticket status.

    `purchases` must be the requesting customer's own purchases; any requested
    ID outside it is `NOT_OWNED`.
    """
    owned = {p.id: p for p in purchases}
    rejected = _ids_on(existing_tickets, TicketStatus.REJECTED)
    active = _ids_on(existing_tickets, TicketStatus.APPROVED) | _ids_on(
        existing_tickets, TicketStatus.PENDING_REVIEW
    )

    items: list[ItemDecision] = []
    amount = 0
    for pid in _dedupe(requested_ids):
        purchase = owned.get(pid)
        reason = _judge(purchase, today, settings, rejected, active)
        items.append(ItemDecision(purchase_id=pid, eligible=reason is None, reason=reason))
        if reason is None and purchase is not None:
            amount += purchase.price_cents

    if not any(i.eligible for i in items):
        return RefundDecision(items=tuple(items), amount_cents=0, status=None)

    prior = _prior_total(existing_tickets, today, settings.running_total_days)
    status = (
        TicketStatus.PENDING_REVIEW
        if prior + amount > settings.review_threshold_cents
        else TicketStatus.APPROVED
    )
    return RefundDecision(items=tuple(items), amount_cents=amount, status=status)
