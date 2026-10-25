"""The per-customer row lock must serialise concurrent refund requests.

Without it, two requests could both read "not yet refunded" and the loser
would hit the unique index as an error instead of a clean ALREADY_REFUNDED
outcome.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from refund_agent.data import PostgresRepository
from refund_agent.policy import (
    DeclineReason,
    FixedClock,
    PolicySettings,
    Profile,
    Purchase,
    Role,
    TicketStatus,
)
from refund_agent.service import RefundOutcome, RefundService
from tests.contract.repository_contract import C_P1, CUSTOMER, PROFILES, PURCHASES
from tests.integration.conftest import Seeder

pytestmark = pytest.mark.integration

# Contract purchases are dated 2026-01-01, so this is inside the window.
TODAY = date(2026, 1, 5)
SETTINGS = PolicySettings(window_days=30, review_threshold_cents=10_000, running_total_days=30)
THREADS = 2


def _race(request: Callable[[], RefundOutcome]) -> list[RefundOutcome]:
    """Run ``request`` on THREADS threads released together by a barrier."""
    start = threading.Barrier(THREADS)

    def run() -> RefundOutcome:
        start.wait()  # release all threads together to maximise contention
        return request()

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        return [f.result() for f in [executor.submit(run) for _ in range(THREADS)]]


def test_concurrent_requests_create_one_ticket(
    pool: ConnectionPool, seed: Seeder, conn: psycopg.Connection[Any]
) -> None:
    seed(PROFILES, PURCHASES, [])
    service = RefundService(PostgresRepository(pool), FixedClock(TODAY), SETTINGS)
    outcomes = _race(lambda: service.request_refund(CUSTOMER, [C_P1]))

    row = conn.execute("select count(*) from refund_tickets").fetchone()
    assert row is not None and row[0] == 1

    winners = [o for o in outcomes if o.ticket is not None]
    losers = [o for o in outcomes if o.ticket is None]
    assert len(winners) == 1 and len(losers) == 1
    assert [i.reason for i in losers[0].decision.items] == [DeclineReason.ALREADY_REFUNDED]


def test_concurrent_split_requests_one_goes_to_review(
    pool: ConnectionPool, seed: Seeder, conn: psycopg.Connection[Any]
) -> None:
    # Different purchases, so the unique index cannot help: only the
    # per-customer lock stops both $60 requests reading a $0 running total.
    customer = Profile(
        id=UUID("00000000-0000-0000-0000-0000000000c9"), display_name="Fran", role=Role.CUSTOMER
    )
    bought = TODAY - timedelta(days=3)
    lamp, canvas = (
        Purchase(
            id=UUID(f"00000000-0000-0000-0000-00000000e00{n}"),
            customer_id=customer.id,
            item_name=name,
            price_cents=6_000,
            purchased_on=bought,
        )
        for n, name in ((1, "desk_lamp"), (2, "canvas"))
    )
    seed([customer], [lamp, canvas], [])
    service = RefundService(PostgresRepository(pool), FixedClock(TODAY), SETTINGS)
    targets = iter([lamp.id, canvas.id])
    lock = threading.Lock()

    def request() -> RefundOutcome:
        with lock:
            pid = next(targets)
        return service.request_refund(customer.id, [pid])

    outcomes = _race(request)

    statuses = sorted(o.ticket.status.value for o in outcomes if o.ticket is not None)
    assert statuses == [TicketStatus.APPROVED.value, TicketStatus.PENDING_REVIEW.value]
    row = conn.execute(
        "select count(*) from refund_tickets where customer_id = %s", (customer.id,)
    ).fetchone()
    assert row == (2,)
