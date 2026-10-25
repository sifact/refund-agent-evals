"""Storage contract for refunds: errors, write model and protocols.

Defined as protocols so the service and evals depend on behaviour, not on a
backend; the in-memory and Postgres implementations satisfy the same contract
tests.
"""

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from refund_agent.policy import DeclineReason, Profile, Purchase, Ticket, TicketStatus


class RepositoryError(Exception):
    """Base class for storage-level failures."""


class TicketNotFoundError(RepositoryError):
    """The referenced ticket does not exist."""


class DuplicateRefundError(RepositoryError):
    """A purchase is already on a non-rejected ticket."""


class InvalidTicketTransitionError(RepositoryError):
    """The ticket is not in a state that allows the requested change."""


class NewTicket(BaseModel):
    """A ticket to create; the repository assigns the ID.

    Only terminal-on-creation outcomes are valid: a ticket is born approved or
    waiting for a human, never rejected.
    """

    model_config = ConfigDict(frozen=True)

    customer_id: UUID
    status: TicketStatus
    amount_cents: int
    purchase_ids: tuple[UUID, ...]
    decision_reasons: dict[str, DeclineReason]
    created_at: AwareDatetime

    @field_validator("status")
    @classmethod
    def _creatable_status(cls, v: TicketStatus) -> TicketStatus:
        """Reject statuses a new ticket can never start in."""
        if v not in (TicketStatus.APPROVED, TicketStatus.PENDING_REVIEW):
            raise ValueError("new ticket must be approved or pending_review")
        return v

    @field_validator("purchase_ids")
    @classmethod
    def _unique_purchases(cls, v: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Reject repeats so both backends fail the same way, before storage."""
        if len(set(v)) != len(v):
            raise ValueError("duplicate purchase_ids on a new ticket")
        return v


class CustomerUnit(Protocol):
    """Work done under one customer's exclusive lock."""

    def purchases(self) -> list[Purchase]:
        """The customer's purchases."""
        ...

    def tickets(self) -> list[Ticket]:
        """The customer's tickets, including ones created in this unit."""
        ...

    def create_ticket(self, t: NewTicket) -> Ticket:
        """Stage a ticket; raises ``DuplicateRefundError`` on a clash."""
        ...


class RefundRepository(Protocol):
    """Everything the service needs from storage."""

    def get_profile(self, user_id: UUID) -> Profile | None:
        """Look up a user, or ``None``."""
        ...

    def list_purchases(self, customer_id: UUID) -> list[Purchase]:
        """A customer's purchases."""
        ...

    def list_tickets(self, customer_id: UUID) -> list[Ticket]:
        """A customer's tickets, newest first."""
        ...

    def list_tickets_by_status(self, status: TicketStatus) -> list[Ticket]:
        """All tickets in a status, oldest first (review queue order)."""
        ...

    def get_ticket(self, ticket_id: UUID) -> Ticket | None:
        """Look up a ticket, or ``None``."""
        ...

    def customer_unit(self, customer_id: UUID) -> AbstractContextManager[CustomerUnit]:
        """Exclusive per-customer unit; commits on clean exit, else rolls back."""
        ...

    def review_ticket(
        self,
        ticket_id: UUID,
        status: TicketStatus,
        reviewer_id: UUID,
        note: str | None,
        reviewed_at: datetime,
    ) -> Ticket:
        """Move a pending ticket to approved/rejected; see error types."""
        ...
