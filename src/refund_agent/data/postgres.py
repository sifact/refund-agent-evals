"""Postgres (Supabase) ``RefundRepository``: the production storage backend.

Guarantees are pushed into the database rather than Python so they hold for
every process and replica:

* a ``SELECT ... FOR UPDATE`` on the customer's profile row serialises refund
  requests per customer for the whole unit;
* the partial unique index ``refund_ticket_items_active_purchase_uq`` makes a
  double refund impossible even if the lock were bypassed.

This module connects with the service role (table owner), which bypasses RLS;
RLS exists to lock out the browser clients, not this backend.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import psycopg
from psycopg import errors
from psycopg.rows import class_row, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from refund_agent.config import Settings
from refund_agent.data.repository import (
    CustomerUnit,
    DuplicateRefundError,
    InvalidTicketTransitionError,
    NewTicket,
    TicketNotFoundError,
)
from refund_agent.policy import Profile, Purchase, Ticket, TicketStatus

_REVIEW_OUTCOMES: Final = (TicketStatus.APPROVED, TicketStatus.REJECTED)
ACTIVE_PURCHASE_CONSTRAINT: Final = "refund_ticket_items_active_purchase_uq"

Conn = psycopg.Connection[Any]

# ---------------------------------------------------------------- SQL
# Columns of a ticket read from alias ``t``; purchase_ids keep request order.
_TICKET_COLUMNS: Final = """
    t.id, t.customer_id, t.status, t.amount_cents, t.decision_reasons, t.created_at,
    t.reviewed_by, t.reviewed_at, t.review_note,
    coalesce(
        (select array_agg(i.purchase_id order by i.position)
           from public.refund_ticket_items i
          where i.ticket_id = t.id),
        '{}'::uuid[]
    ) as purchase_ids
"""
_SELECT_TICKETS: Final = f"select {_TICKET_COLUMNS} from public.refund_tickets t"

_SQL_PROFILE: Final = "select id, display_name, role from public.profiles where id = %s"
_SQL_PURCHASES: Final = """
    select id, customer_id, item_name, price_cents, purchased_on
      from public.purchases
     where customer_id = %s
     order by purchased_on, id
"""
_SQL_TICKETS_BY_CUSTOMER: Final = (
    f"{_SELECT_TICKETS} where t.customer_id = %s order by t.created_at desc, t.id desc"
)
_SQL_TICKETS_BY_STATUS: Final = f"{_SELECT_TICKETS} where t.status = %s order by t.created_at, t.id"
_SQL_TICKET_BY_ID: Final = f"{_SELECT_TICKETS} where t.id = %s"

_SQL_LOCK_CUSTOMER: Final = "select 1 from public.profiles where id = %s for update"
_SQL_INSERT_TICKET: Final = """
    insert into public.refund_tickets
        (id, customer_id, status, amount_cents, decision_reasons, created_at)
    values (%s, %s, %s, %s, %s, %s)
"""
_SQL_INSERT_ITEM: Final = """
    insert into public.refund_ticket_items (ticket_id, purchase_id, position)
    values (%s, %s, %s)
"""
# One guarded UPDATE: the status check and the write are atomic, so two
# reviewers racing on the same ticket cannot both succeed.
_SQL_REVIEW: Final = f"""
    with t as (
        update public.refund_tickets
           set status = %s, reviewed_by = %s, reviewed_at = %s, review_note = %s
         where id = %s and status = 'pending_review'
     returning *
    )
    select {_TICKET_COLUMNS} from t
"""
_SQL_TICKET_STATUS: Final = "select status from public.refund_tickets where id = %s"
_SQL_RELEASE_ITEMS: Final = (
    "update public.refund_ticket_items set active = false where ticket_id = %s"
)


# ---------------------------------------------------------------- helpers
def _fetch_tickets(conn: Conn, query: str, params: tuple[Any, ...]) -> list[Ticket]:
    with conn.cursor(row_factory=dict_row) as cur:
        return [Ticket.model_validate(r) for r in cur.execute(query, params).fetchall()]


def _fetch_purchases(conn: Conn, customer_id: UUID) -> list[Purchase]:
    with conn.cursor(row_factory=class_row(Purchase)) as cur:
        return cur.execute(_SQL_PURCHASES, (customer_id,)).fetchall()


def _is_active_purchase_clash(exc: errors.UniqueViolation) -> bool:
    return exc.diag.constraint_name == ACTIVE_PURCHASE_CONSTRAINT


# ---------------------------------------------------------------- unit
class _PostgresUnit:
    """Reads and writes on the unit's own connection, inside its transaction.

    Using one connection is what makes staged tickets visible to ``tickets()``
    while staying invisible to everyone else until commit.
    """

    def __init__(self, conn: Conn, customer_id: UUID) -> None:
        self._conn = conn
        self._customer_id = customer_id

    def purchases(self) -> list[Purchase]:
        return _fetch_purchases(self._conn, self._customer_id)

    def tickets(self) -> list[Ticket]:
        return _fetch_tickets(self._conn, _SQL_TICKETS_BY_CUSTOMER, (self._customer_id,))

    def create_ticket(self, t: NewTicket) -> Ticket:
        if t.customer_id != self._customer_id:
            raise ValueError("ticket customer does not match the unit's customer")
        ticket = Ticket(id=uuid4(), **t.model_dump())
        try:
            # Savepoint: a clash undoes only this ticket and leaves the unit usable.
            with self._conn.transaction():
                self._conn.execute(
                    _SQL_INSERT_TICKET,
                    (
                        ticket.id,
                        ticket.customer_id,
                        ticket.status.value,
                        ticket.amount_cents,
                        Jsonb(t.model_dump(mode="json")["decision_reasons"]),
                        ticket.created_at,
                    ),
                )
                with self._conn.cursor() as cur:
                    cur.executemany(
                        _SQL_INSERT_ITEM,
                        [(ticket.id, pid, pos) for pos, pid in enumerate(ticket.purchase_ids)],
                    )
        except errors.UniqueViolation as exc:
            if _is_active_purchase_clash(exc):
                raise DuplicateRefundError("purchase already on a non-rejected ticket") from exc
            raise
        return ticket


# ---------------------------------------------------------------- repository
class PostgresRepository:
    """``RefundRepository`` over a psycopg connection pool.

    The pool should be created with ``autocommit=True`` (see ``make_pool``) so
    plain reads never leave idle transactions; units open explicit ones.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def get_profile(self, user_id: UUID) -> Profile | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Profile)) as cur:
            return cur.execute(_SQL_PROFILE, (user_id,)).fetchone()

    def list_purchases(self, customer_id: UUID) -> list[Purchase]:
        with self._pool.connection() as conn:
            return _fetch_purchases(conn, customer_id)

    def list_tickets(self, customer_id: UUID) -> list[Ticket]:
        with self._pool.connection() as conn:
            return _fetch_tickets(conn, _SQL_TICKETS_BY_CUSTOMER, (customer_id,))

    def list_tickets_by_status(self, status: TicketStatus) -> list[Ticket]:
        with self._pool.connection() as conn:
            return _fetch_tickets(conn, _SQL_TICKETS_BY_STATUS, (status.value,))

    def get_ticket(self, ticket_id: UUID) -> Ticket | None:
        with self._pool.connection() as conn:
            found = _fetch_tickets(conn, _SQL_TICKET_BY_ID, (ticket_id,))
        return found[0] if found else None

    @contextmanager
    def customer_unit(self, customer_id: UUID) -> Iterator[CustomerUnit]:
        """Hold the customer's profile row lock until commit or rollback.

        A concurrent unit for the same customer blocks on the lock, then (under
        READ COMMITTED) sees this unit's committed tickets on its next read.
        """
        with self._pool.connection() as conn, conn.transaction():
            conn.execute(_SQL_LOCK_CUSTOMER, (customer_id,))
            yield _PostgresUnit(conn, customer_id)

    def review_ticket(
        self,
        ticket_id: UUID,
        status: TicketStatus,
        reviewer_id: UUID,
        note: str | None,
        reviewed_at: datetime,
    ) -> Ticket:
        if status not in _REVIEW_OUTCOMES:
            raise ValueError("review status must be approved or rejected")
        with self._pool.connection() as conn, conn.transaction():
            found = _fetch_tickets(
                conn, _SQL_REVIEW, (status.value, reviewer_id, reviewed_at, note, ticket_id)
            )
            if not found:
                raise self._review_failure(conn, ticket_id)
            if status is TicketStatus.REJECTED:
                # Same transaction: the purchases are freed exactly when the
                # rejection becomes visible.
                conn.execute(_SQL_RELEASE_ITEMS, (ticket_id,))
            return found[0]

    @staticmethod
    def _review_failure(conn: Conn, ticket_id: UUID) -> Exception:
        """Tell a missing ticket apart from one that is no longer pending."""
        row = conn.execute(_SQL_TICKET_STATUS, (ticket_id,)).fetchone()
        if row is None:
            return TicketNotFoundError(str(ticket_id))
        return InvalidTicketTransitionError(f"cannot review a {row[0]} ticket")


def make_pool(settings: Settings) -> ConnectionPool:
    """Open the app's connection pool, failing fast if no database is configured."""
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not set; cannot connect to Postgres")
    return ConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=1,
        max_size=settings.db_pool_max_size,
        kwargs={"autocommit": True},
        check=ConnectionPool.check_connection,
        open=True,
    )
