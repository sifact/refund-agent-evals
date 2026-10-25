"""Tests for the refund policy rules."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from hypothesis import given
from hypothesis import strategies as st

from refund_agent.policy import (
    DeclineReason,
    Purchase,
    Ticket,
    TicketStatus,
)
from refund_agent.policy.rules import PolicySettings, decide_refund

C = uuid4()
D = uuid4()
TODAY = date(2026, 10, 15)
S = PolicySettings(30, 10000, 30)


def p(name: str, price: int, days_ago: int, customer: UUID = C) -> Purchase:
    return Purchase(
        id=uuid4(),
        customer_id=customer,
        item_name=name,
        price_cents=price,
        purchased_on=TODAY - timedelta(days=days_ago),
    )


def ticket(status: TicketStatus, amount: int, purchases: tuple[UUID, ...], days_ago: int) -> Ticket:
    created = datetime(2026, 10, 15, 12, tzinfo=UTC) - timedelta(days=days_ago)
    return Ticket(
        id=uuid4(),
        customer_id=C,
        status=status,
        amount_cents=amount,
        purchase_ids=purchases,
        decision_reasons={},
        created_at=created,
    )


def test_day_zero_eligible() -> None:
    a = p("a", 1000, 0)
    assert decide_refund([a], [a.id], [], TODAY, S).eligible_ids == (a.id,)


def test_day_30_eligible() -> None:
    a = p("a", 1000, 30)
    assert decide_refund([a], [a.id], [], TODAY, S).eligible_ids == (a.id,)


def test_day_31_outside_window() -> None:
    a = p("a", 1000, 31)
    d = decide_refund([a], [a.id], [], TODAY, S)
    assert d.items[0].reason is DeclineReason.OUTSIDE_WINDOW


def test_future_date() -> None:
    a = p("a", 1000, -1)
    d = decide_refund([a], [a.id], [], TODAY, S)
    assert d.items[0].reason is DeclineReason.FUTURE_DATE


def test_mixed_request_tickets_only_eligible() -> None:
    backpack = p("backpack", 4500, 13)
    bottle = p("water_bottle", 1800, 82)
    d = decide_refund([backpack, bottle], [backpack.id, bottle.id], [], TODAY, S)
    assert d.amount_cents == 4500
    assert d.eligible_ids == (backpack.id,)
    assert d.status is TicketStatus.APPROVED
    assert d.items[1].reason is DeclineReason.OUTSIDE_WINDOW


def test_none_eligible_no_status() -> None:
    a = p("a", 1000, 90)
    d = decide_refund([a], [a.id], [], TODAY, S)
    assert d.status is None
    assert d.amount_cents == 0


def test_exactly_threshold_auto_approved() -> None:
    a = p("a", 10000, 1)
    assert decide_refund([a], [a.id], [], TODAY, S).status is TicketStatus.APPROVED


def test_one_cent_over_goes_to_review() -> None:
    a = p("a", 10001, 1)
    assert decide_refund([a], [a.id], [], TODAY, S).status is TicketStatus.PENDING_REVIEW


def test_running_total_split_goes_to_review() -> None:
    old, new = p("old", 6000, 5), p("new", 6000, 1)
    t = ticket(TicketStatus.APPROVED, 6000, (old.id,), 5)
    d = decide_refund([old, new], [new.id], [t], TODAY, S)
    assert d.status is TicketStatus.PENDING_REVIEW


def test_old_ticket_outside_running_window_ignored() -> None:
    old, new = p("old", 6000, 31), p("new", 6000, 1)
    t = ticket(TicketStatus.APPROVED, 6000, (old.id,), 31)
    d = decide_refund([old, new], [new.id], [t], TODAY, S)
    assert d.status is TicketStatus.APPROVED


def test_rejected_ticket_not_counted_in_running_total() -> None:
    old, new = p("old", 6000, 5), p("new", 6000, 1)
    t = ticket(TicketStatus.REJECTED, 6000, (old.id,), 5)
    d = decide_refund([old, new], [new.id], [t], TODAY, S)
    assert d.status is TicketStatus.APPROVED


def test_pending_ticket_counted_in_running_total() -> None:
    old, new = p("old", 6000, 5), p("new", 6000, 1)
    t = ticket(TicketStatus.PENDING_REVIEW, 6000, (old.id,), 5)
    d = decide_refund([old, new], [new.id], [t], TODAY, S)
    assert d.status is TicketStatus.PENDING_REVIEW


def test_already_refunded() -> None:
    a = p("a", 1000, 1)
    t = ticket(TicketStatus.APPROVED, 1000, (a.id,), 1)
    d = decide_refund([a], [a.id], [t], TODAY, S)
    assert d.items[0].reason is DeclineReason.ALREADY_REFUNDED
    t2 = ticket(TicketStatus.PENDING_REVIEW, 1000, (a.id,), 1)
    d2 = decide_refund([a], [a.id], [t2], TODAY, S)
    assert d2.items[0].reason is DeclineReason.ALREADY_REFUNDED


def test_previously_rejected() -> None:
    a = p("a", 1000, 1)
    t = ticket(TicketStatus.REJECTED, 1000, (a.id,), 1)
    d = decide_refund([a], [a.id], [t], TODAY, S)
    assert d.items[0].reason is DeclineReason.PREVIOUSLY_REJECTED


def test_rejected_takes_precedence_over_approved() -> None:
    a = p("a", 1000, 1)
    ts = [
        ticket(TicketStatus.APPROVED, 1000, (a.id,), 1),
        ticket(TicketStatus.REJECTED, 1000, (a.id,), 2),
    ]
    d = decide_refund([a], [a.id], ts, TODAY, S)
    assert d.items[0].reason is DeclineReason.PREVIOUSLY_REJECTED


def test_duplicate_requested_ids_counted_once() -> None:
    a = p("a", 1234, 1)
    d = decide_refund([a], [a.id, a.id], [], TODAY, S)
    assert len(d.items) == 1
    assert d.amount_cents == a.price_cents


def test_other_customers_purchase_is_not_owned() -> None:
    mine = p("mine", 1000, 1)
    theirs = p("theirs", 1000, 1, customer=D)
    d = decide_refund([mine], [theirs.id], [], TODAY, S)
    assert d.items[0].reason is DeclineReason.NOT_OWNED
    assert d.status is None


def test_empty_request() -> None:
    d = decide_refund([p("a", 1000, 1)], [], [], TODAY, S)
    assert d.items == ()
    assert d.status is None


@given(
    data=st.lists(st.tuples(st.integers(1, 20000), st.integers(-5, 60)), min_size=0, max_size=8),
    picks=st.lists(st.integers(0, 9), max_size=10),
)
def test_ticket_never_contains_ineligible_item(
    data: list[tuple[int, int]], picks: list[int]
) -> None:
    purchases = [p(f"i{n}", price, age) for n, (price, age) in enumerate(data)]
    stranger = p("x", 100, 1, customer=D)
    pool = [*purchases, stranger]
    requested = [pool[i % len(pool)].id for i in picks]
    d = decide_refund(purchases, requested, [], TODAY, S)
    by_id = {x.id: x for x in purchases}
    for pid in d.eligible_ids:
        assert pid in by_id
        assert 0 <= (TODAY - by_id[pid].purchased_on).days <= S.window_days
    assert d.amount_cents == sum(by_id[i].price_cents for i in d.eligible_ids)
