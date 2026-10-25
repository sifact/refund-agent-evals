"""Frozen domain models shared by the policy, agent and persistence layers.

Everything is immutable so a decision, once computed, cannot be altered on its
way to the database or the audit log.
"""

from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)


class Role(StrEnum):
    """Who is acting; drives authorisation of review actions."""

    CUSTOMER = "customer"
    STAFF = "staff"


class TicketStatus(StrEnum):
    """Lifecycle state of a refund ticket."""

    APPROVED = "approved"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"


class DeclineReason(StrEnum):
    """Machine-readable reason a purchase was not refundable."""

    NOT_OWNED = "not_owned"
    OUTSIDE_WINDOW = "outside_window"
    FUTURE_DATE = "future_date"
    ALREADY_REFUNDED = "already_refunded"
    PREVIOUSLY_REJECTED = "previously_rejected"


class _Frozen(BaseModel):
    """Base class: immutable so decisions cannot be mutated after creation."""

    model_config = ConfigDict(frozen=True)


class Profile(_Frozen):
    """A user of the system."""

    id: UUID
    display_name: str
    role: Role


class Purchase(_Frozen):
    """A single purchased item; price is positive so refunds are never free."""

    id: UUID
    customer_id: UUID
    item_name: str
    price_cents: PositiveInt
    purchased_on: date


class Ticket(_Frozen):
    """A persisted refund request and its outcome."""

    id: UUID
    customer_id: UUID
    status: TicketStatus
    amount_cents: NonNegativeInt
    purchase_ids: tuple[UUID, ...]
    # Keys are declined purchase IDs as str, so the mapping serialises to JSON.
    decision_reasons: dict[str, DeclineReason]
    created_at: AwareDatetime
    reviewed_by: UUID | None = None
    reviewed_at: AwareDatetime | None = None
    review_note: str | None = None


class ItemDecision(_Frozen):
    """Eligibility verdict for one purchase."""

    purchase_id: UUID
    eligible: bool
    reason: DeclineReason | None

    @model_validator(mode="after")
    def _reason_matches_eligibility(self) -> "ItemDecision":
        """Keep verdicts self-consistent: a decline always says why."""
        if self.eligible and self.reason is not None:
            raise ValueError("eligible item must not have a decline reason")
        if not self.eligible and self.reason is None:
            raise ValueError("ineligible item requires a decline reason")
        return self


class RefundDecision(_Frozen):
    """Aggregate verdict for a refund request."""

    items: tuple[ItemDecision, ...]
    amount_cents: NonNegativeInt
    status: TicketStatus | None

    @property
    def eligible_ids(self) -> tuple[UUID, ...]:
        """IDs of purchases that passed every rule, in request order."""
        return tuple(i.purchase_id for i in self.items if i.eligible)
