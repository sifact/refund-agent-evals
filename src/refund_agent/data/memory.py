"""Thread-safe in-memory ``RefundRepository`` for the service tests and evals."""

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID, uuid4

from refund_agent.data.repository import (
    CustomerUnit,
    DuplicateRefundError,
    InvalidTicketTransitionError,
    NewTicket,
    TicketNotFoundError,
)
from refund_agent.policy import Profile, Purchase, Ticket, TicketStatus

_REVIEW_OUTCOMES = (TicketStatus.APPROVED, TicketStatus.REJECTED)


class _Unit:
    """Stages writes so an exception leaves the store untouched."""

    def __init__(self, repo: "InMemoryRepository", customer_id: UUID) -> None:
        self._repo = repo
        self._customer_id = customer_id
        self.staged: list[Ticket] = []

    def purchases(self) -> list[Purchase]:
        return self._repo.list_purchases(self._customer_id)

    def tickets(self) -> list[Ticket]:
        return self._repo.list_tickets(self._customer_id) + self.staged

    def create_ticket(self, t: NewTicket) -> Ticket:
        if t.customer_id != self._customer_id:
            raise ValueError("ticket customer does not match the unit's customer")
        # Global check (like a partial unique index): a purchase may sit on at
        # most one non-rejected ticket. Rejected tickets free their purchases;
        # the policy, not storage, blocks re-requests.
        taken = self._repo.active_purchase_ids() | {
            pid
            for tk in self.staged
            if tk.status is not TicketStatus.REJECTED
            for pid in tk.purchase_ids
        }
        if taken.intersection(t.purchase_ids):
            raise DuplicateRefundError("purchase already on a non-rejected ticket")
        ticket = Ticket(id=uuid4(), **t.model_dump())
        self.staged.append(ticket)
        return ticket


class InMemoryRepository:
    """Per-customer locks serialise units; a store lock guards the dicts."""

    def __init__(
        self,
        profiles: Iterable[Profile] = (),
        purchases: Iterable[Purchase] = (),
        tickets: Iterable[Ticket] = (),
    ) -> None:
        self._profiles = {p.id: p for p in profiles}
        self._purchases = list(purchases)
        # dict preserves insertion order, used as the tie-breaker for sorting.
        self._tickets = {t.id: t for t in tickets}
        self._store_lock = threading.Lock()
        self._customer_locks: dict[UUID, threading.Lock] = {}

    def _lock_for(self, customer_id: UUID) -> threading.Lock:
        with self._store_lock:
            return self._customer_locks.setdefault(customer_id, threading.Lock())

    def active_purchase_ids(self) -> set[UUID]:
        """Purchase IDs on committed, non-rejected tickets across all customers."""
        with self._store_lock:
            return {
                pid
                for t in self._tickets.values()
                if t.status is not TicketStatus.REJECTED
                for pid in t.purchase_ids
            }

    def get_profile(self, user_id: UUID) -> Profile | None:
        return self._profiles.get(user_id)

    def list_purchases(self, customer_id: UUID) -> list[Purchase]:
        return [p for p in self._purchases if p.customer_id == customer_id]

    def list_tickets(self, customer_id: UUID) -> list[Ticket]:
        with self._store_lock:
            rows = [t for t in self._tickets.values() if t.customer_id == customer_id]
        # Stable sort on reversed input: ties resolve newest-inserted first.
        return sorted(reversed(rows), key=lambda t: t.created_at, reverse=True)

    def list_tickets_by_status(self, status: TicketStatus) -> list[Ticket]:
        with self._store_lock:
            rows = [t for t in self._tickets.values() if t.status is status]
        return sorted(rows, key=lambda t: t.created_at)

    def get_ticket(self, ticket_id: UUID) -> Ticket | None:
        with self._store_lock:
            return self._tickets.get(ticket_id)

    @contextmanager
    def customer_unit(self, customer_id: UUID) -> Iterator[CustomerUnit]:
        with self._lock_for(customer_id):
            unit = _Unit(self, customer_id)
            yield unit
            # Reached only on a clean exit; an exception skips the commit.
            with self._store_lock:
                for ticket in unit.staged:
                    self._tickets[ticket.id] = ticket

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
        with self._store_lock:
            current = self._tickets.get(ticket_id)
            if current is None:
                raise TicketNotFoundError(str(ticket_id))
            if current.status is not TicketStatus.PENDING_REVIEW:
                raise InvalidTicketTransitionError(f"cannot review a {current.status.value} ticket")
            updated = current.model_copy(
                update={
                    "status": status,
                    "reviewed_by": reviewer_id,
                    "reviewed_at": reviewed_at,
                    "review_note": note,
                }
            )
            self._tickets[ticket_id] = updated
            return updated
