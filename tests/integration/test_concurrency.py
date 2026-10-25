"""The per-customer row lock must serialise concurrent refund requests.

Without it, two requests could both read "not yet refunded" and the loser
would hit the unique index as an error instead of a clean ALREADY_REFUNDED
outcome.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from refund_agent.data import PostgresRepository
from refund_agent.policy import DeclineReason, FixedClock, PolicySettings
from refund_agent.service import RefundOutcome, RefundService
from tests.contract.repository_contract import C_P1, CUSTOMER, PROFILES, PURCHASES
from tests.integration.conftest import Seeder

pytestmark = pytest.mark.integration

# Contract purchases are dated 2026-01-01, so this is inside the window.
TODAY = date(2026, 1, 5)
SETTINGS = PolicySettings(window_days=30, review_threshold_cents=10_000, running_total_days=30)
THREADS = 2


def test_concurrent_requests_create_one_ticket(
    pool: ConnectionPool, seed: Seeder, conn: psycopg.Connection[Any]
) -> None:
    seed(PROFILES, PURCHASES, [])
    service = RefundService(PostgresRepository(pool), FixedClock(TODAY), SETTINGS)
    start = threading.Barrier(THREADS)

    def request() -> RefundOutcome:
        start.wait()  # release both threads together to maximise contention
        return service.request_refund(CUSTOMER, [C_P1])

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        outcomes = [f.result() for f in [executor.submit(request) for _ in range(THREADS)]]

    row = conn.execute("select count(*) from refund_tickets").fetchone()
    assert row is not None and row[0] == 1

    winners = [o for o in outcomes if o.ticket is not None]
    losers = [o for o in outcomes if o.ticket is None]
    assert len(winners) == 1 and len(losers) == 1
    assert [i.reason for i in losers[0].decision.items] == [DeclineReason.ALREADY_REFUNDED]
