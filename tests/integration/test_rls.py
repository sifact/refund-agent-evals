"""Row-level security: clients read only their own rows and can never write.

These run as the ``anon`` / ``authenticated`` roles with JWT claims set exactly
as PostgREST sets them, so they prove what a browser holding a Supabase key
could see or do.
"""

from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import errors

from refund_agent.policy import Ticket, TicketStatus
from tests.contract.repository_contract import (
    CUSTOMER,
    O_P1,
    OTHER,
    PROFILES,
    PURCHASES,
    STAFF,
    T0,
)
from tests.integration.conftest import ActAs, Seeder

pytestmark = pytest.mark.integration

APP_TABLES = ("profiles", "purchases", "refund_tickets", "refund_ticket_items")

OTHER_TICKET = Ticket(
    id=UUID("00000000-0000-0000-0000-00000000bb02"),
    customer_id=OTHER,
    status=TicketStatus.APPROVED,
    amount_cents=3000,
    purchase_ids=(O_P1,),
    decision_reasons={},
    created_at=T0,
)


@pytest.fixture(autouse=True)
def _seeded(seed: Seeder) -> None:
    seed(PROFILES, PURCHASES, [OTHER_TICKET])


def _count(conn: psycopg.Connection[Any], table: str) -> int:
    row = conn.execute(f"select count(*) from {table}").fetchone()
    assert row is not None
    return int(row[0])


def _ids(conn: psycopg.Connection[Any], query: str) -> set[UUID]:
    return {r[0] for r in conn.execute(query).fetchall()}


def test_rls_customer_sees_only_own_rows(conn: psycopg.Connection[Any], act_as: ActAs) -> None:
    own_purchases = sum(1 for p in PURCHASES if p.customer_id == CUSTOMER)
    with act_as(conn, "authenticated", CUSTOMER):
        assert _count(conn, "purchases") == own_purchases
        assert _ids(conn, "select customer_id from purchases") == {CUSTOMER}
        assert _ids(conn, "select id from profiles") == {CUSTOMER}
        # OTHER's ticket and its items are invisible.
        assert _count(conn, "refund_tickets") == 0
        assert _count(conn, "refund_ticket_items") == 0


def test_rls_owner_sees_own_ticket_and_items(conn: psycopg.Connection[Any], act_as: ActAs) -> None:
    with act_as(conn, "authenticated", OTHER):
        assert _ids(conn, "select id from refund_tickets") == {OTHER_TICKET.id}
        assert _ids(conn, "select purchase_id from refund_ticket_items") == {O_P1}


def test_rls_staff_sees_all(conn: psycopg.Connection[Any], act_as: ActAs) -> None:
    with act_as(conn, "authenticated", STAFF):
        assert _count(conn, "profiles") == len(PROFILES)
        assert _count(conn, "purchases") == len(PURCHASES)
        assert _count(conn, "refund_tickets") == 1
        assert _count(conn, "refund_ticket_items") == 1


def test_rls_client_cannot_insert_ticket(conn: psycopg.Connection[Any], act_as: ActAs) -> None:
    with (
        pytest.raises(errors.InsufficientPrivilege),
        act_as(conn, "authenticated", CUSTOMER),
    ):
        conn.execute(
            "insert into refund_tickets (customer_id, status, amount_cents)"
            " values (%s, 'approved', 1000)",
            (CUSTOMER,),
        )


@pytest.mark.parametrize(
    "statement",
    [
        "update refund_tickets set status = 'approved'",
        "delete from refund_tickets",
        "update refund_ticket_items set active = false",
        "update profiles set role = 'staff'",
        "delete from purchases",
    ],
)
def test_rls_client_cannot_update_or_delete(
    conn: psycopg.Connection[Any], act_as: ActAs, statement: str
) -> None:
    with pytest.raises(errors.InsufficientPrivilege), act_as(conn, "authenticated", STAFF):
        conn.execute(statement)


@pytest.mark.parametrize("table", APP_TABLES)
def test_rls_anon_cannot_read(conn: psycopg.Connection[Any], act_as: ActAs, table: str) -> None:
    # anon holds no privileges at all, so reads fail before RLS is consulted.
    with pytest.raises(errors.InsufficientPrivilege), act_as(conn, "anon"):
        _count(conn, table)


CLIENT_WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def _has(conn: psycopg.Connection[Any], role: str, table: str, privilege: str) -> bool:
    row = conn.execute(
        "select has_table_privilege(%s, %s, %s)", (role, f"public.{table}", privilege)
    ).fetchone()
    assert row is not None
    return bool(row[0])


def test_client_roles_have_only_select(conn: psycopg.Connection[Any]) -> None:
    for table in APP_TABLES:
        assert _has(conn, "authenticated", table, "SELECT"), table
        for privilege in CLIENT_WRITE_PRIVILEGES:
            assert not _has(conn, "authenticated", table, privilege), (table, privilege)
        for privilege in ("SELECT", *CLIENT_WRITE_PRIVILEGES):
            assert not _has(conn, "anon", table, privilege), (table, privilege)


def test_is_staff_executable_only_by_authenticated(conn: psycopg.Connection[Any]) -> None:
    def can_execute(role: str) -> bool:
        row = conn.execute(
            "select has_function_privilege(%s, 'public.is_staff()', 'EXECUTE')", (role,)
        ).fetchone()
        assert row is not None
        return bool(row[0])

    assert can_execute("authenticated")
    assert not can_execute("anon")
    assert not can_execute("public")


@pytest.mark.parametrize(
    ("positions", "error"),
    [((-1,), errors.CheckViolation), ((0, 0), errors.UniqueViolation)],
)
def test_ticket_item_positions_are_valid_and_unique(
    conn: psycopg.Connection[Any], positions: tuple[int, ...], error: type[Exception]
) -> None:
    ticket_id = UUID("00000000-0000-0000-0000-00000000bb03")
    conn.execute(
        "insert into refund_tickets (id, customer_id, status, amount_cents)"
        " values (%s, %s, 'pending_review', 3000)",
        (ticket_id, CUSTOMER),
    )
    purchases = [p.id for p in PURCHASES if p.customer_id == CUSTOMER]
    with pytest.raises(error), conn.transaction():
        for pid, position in zip(purchases, positions, strict=False):
            conn.execute(
                "insert into refund_ticket_items (ticket_id, purchase_id, position)"
                " values (%s, %s, %s)",
                (ticket_id, pid, position),
            )
