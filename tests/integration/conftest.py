"""Fixtures for tests against the local Supabase Postgres (``supabase start``).

Why truncate instead of per-test transactions: the repository opens its own
pooled connections and commits, so the only reliable isolation is a clean
slate before every test.
"""

import json
import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from refund_agent.policy import Profile, Purchase, Ticket, TicketStatus
from tests.integration.db_guard import assert_local_database

# Deliberately NOT ``DATABASE_URL``: that is the app's (possibly production)
# database, and these tests truncate tables.
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
# Marks fixture users so cleanup never touches real local auth users.
TEST_EMAIL_DOMAIN = "refund-tests.invalid"

APP_TABLES = "refund_ticket_items, refund_tickets, purchases, profiles"

Seeder = Callable[[Iterable[Profile], Iterable[Purchase], Iterable[Ticket]], None]
ActAs = Callable[[psycopg.Connection[Any], str, UUID | None], AbstractContextManager[None]]


@pytest.fixture(scope="session")
def database_url() -> str:
    """The only source of connection URLs here; checked before any connect."""
    url = os.environ.get(TEST_DATABASE_URL_ENV, DEFAULT_TEST_DATABASE_URL)
    try:
        assert_local_database(url)
    except RuntimeError as exc:
        pytest.exit(str(exc), returncode=pytest.ExitCode.USAGE_ERROR)
    return url


@pytest.fixture(scope="session")
def pool(database_url: str) -> Iterator[ConnectionPool]:
    """At least two connections so concurrent units can really contend."""
    with ConnectionPool(
        database_url, min_size=2, max_size=4, kwargs={"autocommit": True}, open=True
    ) as p:
        yield p


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection[Any]]:
    """A raw admin connection for seeding, assertions and RLS role switching."""
    with psycopg.connect(database_url, autocommit=True) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"truncate {APP_TABLES} cascade")
    conn.execute("delete from auth.users where email like %s", (f"%@{TEST_EMAIL_DOMAIN}",))


@pytest.fixture
def seed(conn: psycopg.Connection[Any]) -> Seeder:
    """Insert auth users, profiles, purchases and tickets (with their items)."""

    def _seed(
        profiles: Iterable[Profile],
        purchases: Iterable[Purchase],
        tickets: Iterable[Ticket] = (),
    ) -> None:
        with conn.transaction():
            for p in profiles:
                conn.execute(
                    "insert into auth.users (id, email, aud, role) "
                    "values (%s, %s, 'authenticated', 'authenticated')",
                    (p.id, f"{p.id}@{TEST_EMAIL_DOMAIN}"),
                )
                conn.execute(
                    "insert into profiles (id, display_name, role) values (%s, %s, %s)",
                    (p.id, p.display_name, p.role.value),
                )
            for pu in purchases:
                conn.execute(
                    "insert into purchases (id, customer_id, item_name, price_cents, purchased_on)"
                    " values (%s, %s, %s, %s, %s)",
                    (pu.id, pu.customer_id, pu.item_name, pu.price_cents, pu.purchased_on),
                )
            for t in tickets:
                conn.execute(
                    "insert into refund_tickets (id, customer_id, status, amount_cents,"
                    " decision_reasons, created_at, reviewed_by, reviewed_at, review_note)"
                    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        t.id,
                        t.customer_id,
                        t.status.value,
                        t.amount_cents,
                        Jsonb({k: v.value for k, v in t.decision_reasons.items()}),
                        t.created_at,
                        t.reviewed_by,
                        t.reviewed_at,
                        t.review_note,
                    ),
                )
                for position, pid in enumerate(t.purchase_ids):
                    conn.execute(
                        "insert into refund_ticket_items (ticket_id, purchase_id, active, position)"
                        " values (%s, %s, %s, %s)",
                        (t.id, pid, t.status is not TicketStatus.REJECTED, position),
                    )

    return _seed


@pytest.fixture
def act_as() -> ActAs:
    """Run a block as a Supabase client role, the way PostgREST would.

    The transaction is always rolled back so role and claims never leak.
    """

    @contextmanager
    def _act_as(c: psycopg.Connection[Any], role: str, sub: UUID | None = None) -> Iterator[None]:
        with c.transaction(force_rollback=True):
            c.execute(f"set local role {role}")
            claims = {"role": role} if sub is None else {"sub": str(sub), "role": role}
            c.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
            yield

    return _act_as
