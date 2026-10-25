"""Tests for the frozen domain models."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from refund_agent.policy import (
    DeclineReason,
    ItemDecision,
    Purchase,
    RefundDecision,
    Ticket,
    TicketStatus,
)


def test_purchase_rejects_non_positive_price() -> None:
    with pytest.raises(ValidationError):
        Purchase(
            id=uuid4(),
            customer_id=uuid4(),
            item_name="Mug",
            price_cents=0,
            purchased_on=date(2026, 10, 1),
        )


def test_item_decision_requires_reason_when_ineligible() -> None:
    with pytest.raises(ValidationError):
        ItemDecision(purchase_id=uuid4(), eligible=False, reason=None)


def test_item_decision_rejects_reason_when_eligible() -> None:
    with pytest.raises(ValidationError):
        ItemDecision(purchase_id=uuid4(), eligible=True, reason=DeclineReason.NOT_OWNED)


def test_ticket_is_frozen() -> None:
    ticket = Ticket(
        id=uuid4(),
        customer_id=uuid4(),
        status=TicketStatus.APPROVED,
        amount_cents=100,
        purchase_ids=(uuid4(),),
        decision_reasons={},
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        ticket.amount_cents = 1  # type: ignore[misc]


def test_refund_decision_eligible_ids() -> None:
    ok, bad = uuid4(), uuid4()
    decision = RefundDecision(
        items=(
            ItemDecision(purchase_id=ok, eligible=True, reason=None),
            ItemDecision(purchase_id=bad, eligible=False, reason=DeclineReason.OUTSIDE_WINDOW),
        ),
        amount_cents=100,
        status=TicketStatus.APPROVED,
    )
    assert decision.eligible_ids == (ok,)
