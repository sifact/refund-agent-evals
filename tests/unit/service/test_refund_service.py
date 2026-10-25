"""RefundService is the sole write path; these tests pin its guarantees."""

import inspect
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from refund_agent.config import Settings
from refund_agent.data import InMemoryRepository, InvalidTicketTransitionError
from refund_agent.policy import (
    DeclineReason,
    FixedClock,
    PolicySettings,
    Profile,
    Purchase,
    Role,
    SystemClock,
    TicketStatus,
)
from refund_agent.service import RefundService, build_refund_service

TODAY = date(2026, 10, 15)
SETTINGS = PolicySettings(window_days=30, review_threshold_cents=10_000, running_total_days=30)


class MutableClock:
    """Test clock whose day can be advanced, to prove review ignores the window."""

    def __init__(self, day: date) -> None:
        self.day = day

    def today(self) -> date:
        return self.day

    def now(self) -> datetime:
        return datetime.combine(self.day, time(12), tzinfo=UTC)


CUSTOMER = Profile(id=uuid4(), display_name="Cust", role=Role.CUSTOMER)
STAFF = Profile(id=uuid4(), display_name="Staff", role=Role.STAFF)


def _purchase(price: int, age_days: int = 1) -> Purchase:
    return Purchase(
        id=uuid4(),
        customer_id=CUSTOMER.id,
        item_name="Thing",
        price_cents=price,
        purchased_on=TODAY - timedelta(days=age_days),
    )


def _service(
    purchases: list[Purchase], clock: FixedClock | MutableClock | None = None
) -> RefundService:
    repo = InMemoryRepository([CUSTOMER, STAFF], purchases, [])
    return RefundService(repo, clock or FixedClock(TODAY), SETTINGS)


def test_request_refund_creates_ticket_with_computed_amount() -> None:
    p = _purchase(4_321)
    svc = _service([p])
    params = inspect.signature(RefundService.request_refund).parameters
    assert not any("amount" in name for name in params)
    outcome = svc.request_refund(CUSTOMER.id, [p.id])
    assert outcome.ticket is not None
    assert outcome.ticket.amount_cents == 4_321
    assert outcome.ticket.status is TicketStatus.APPROVED


def test_ineligible_request_creates_no_ticket() -> None:
    p = _purchase(1_000, age_days=90)
    svc = _service([p])
    outcome = svc.request_refund(CUSTOMER.id, [p.id])
    assert outcome.ticket is None
    assert svc.list_tickets(CUSTOMER.id) == []


def test_second_split_request_goes_to_review() -> None:
    a, b = _purchase(6_000), _purchase(6_000)
    svc = _service([a, b])
    first = svc.request_refund(CUSTOMER.id, [a.id])
    second = svc.request_refund(CUSTOMER.id, [b.id])
    assert first.ticket is not None and first.ticket.status is TicketStatus.APPROVED
    assert second.ticket is not None and second.ticket.status is TicketStatus.PENDING_REVIEW


def test_repeat_request_after_rejection_is_declined() -> None:
    p = _purchase(15_000)
    svc = _service([p])
    first = svc.request_refund(CUSTOMER.id, [p.id])
    assert first.ticket is not None
    svc.review(first.ticket.id, STAFF, approve=False, note="no")
    again = svc.request_refund(CUSTOMER.id, [p.id])
    assert again.ticket is None
    assert again.decision.items[0].reason is DeclineReason.PREVIOUSLY_REJECTED
    assert len(svc.list_tickets(CUSTOMER.id)) == 1


def test_review_requires_staff() -> None:
    p = _purchase(15_000)
    svc = _service([p])
    outcome = svc.request_refund(CUSTOMER.id, [p.id])
    assert outcome.ticket is not None
    with pytest.raises(PermissionError):
        svc.review(outcome.ticket.id, CUSTOMER, approve=True, note=None)
    assert [t.id for t in svc.list_pending()] == [outcome.ticket.id]


def test_review_does_not_recheck_window() -> None:
    clock = MutableClock(TODAY)
    p = _purchase(15_000, age_days=29)
    svc = _service([p], clock)
    outcome = svc.request_refund(CUSTOMER.id, [p.id])
    assert outcome.ticket is not None
    assert outcome.ticket.status is TicketStatus.PENDING_REVIEW
    clock.day = TODAY + timedelta(days=10)
    reviewed = svc.review(outcome.ticket.id, STAFF, approve=True, note="ok")
    assert reviewed.status is TicketStatus.APPROVED
    assert reviewed.reviewed_by == STAFF.id


def test_review_already_approved_raises() -> None:
    p = _purchase(15_000)
    svc = _service([p])
    outcome = svc.request_refund(CUSTOMER.id, [p.id])
    assert outcome.ticket is not None
    svc.review(outcome.ticket.id, STAFF, approve=True, note=None)
    with pytest.raises(InvalidTicketTransitionError):
        svc.review(outcome.ticket.id, STAFF, approve=True, note=None)


def test_check_eligibility_is_read_only() -> None:
    p = _purchase(1_000)
    svc = _service([p])
    decision = svc.check_eligibility(CUSTOMER.id, [p.id])
    assert decision.eligible_ids == [p.id] or tuple(decision.eligible_ids) == (p.id,)
    assert svc.list_tickets(CUSTOMER.id) == []
    assert svc.list_purchases(CUSTOMER.id) == [p]


def test_unknown_id_is_declined_not_owned() -> None:
    svc = _service([])
    ghost: UUID = uuid4()
    outcome = svc.request_refund(CUSTOMER.id, [ghost])
    assert outcome.ticket is None
    assert outcome.decision.items[0].reason is DeclineReason.NOT_OWNED


def test_split_refund_reviewed_in_far_east_timezone() -> None:
    # UTC+14: noon UTC would be the next local day, so a FixedClock that
    # ignored the zone produced a "future" ticket the running total skipped.
    zone = "Pacific/Kiritimati"
    a, b = _purchase(6_000), _purchase(6_000)
    repo = InMemoryRepository([CUSTOMER, STAFF], [a, b], [])
    settings = PolicySettings(
        window_days=30, review_threshold_cents=10_000, running_total_days=30, timezone=zone
    )
    svc = RefundService(repo, FixedClock(TODAY, zone), settings)
    first = svc.request_refund(CUSTOMER.id, [a.id])
    second = svc.request_refund(CUSTOMER.id, [b.id])
    assert first.ticket is not None and first.ticket.status is TicketStatus.APPROVED
    assert second.ticket is not None and second.ticket.status is TicketStatus.PENDING_REVIEW


def test_build_refund_service_shares_timezone() -> None:
    settings = Settings(timezone="Pacific/Kiritimati")
    repo = InMemoryRepository([CUSTOMER, STAFF], [], [])
    svc = build_refund_service(repo, settings)
    assert isinstance(svc, RefundService)
    assert svc.settings == PolicySettings.from_settings(settings)
    assert isinstance(svc.clock, SystemClock)
    assert svc.clock.timezone == "Pacific/Kiritimati"
    fixed = FixedClock(TODAY)
    assert build_refund_service(repo, settings, fixed).clock is fixed
