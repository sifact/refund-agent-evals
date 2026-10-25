"""RefundService: the only path that creates or reviews refund tickets.

The agent's tools and the HTTP API both go through here, so the amount is
always computed from stored prices and never accepted from a caller.
"""

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from refund_agent.config import Settings
from refund_agent.data import NewTicket, RefundRepository
from refund_agent.policy import (
    Clock,
    PolicySettings,
    Purchase,
    RefundDecision,
    Role,
    SystemClock,
    Ticket,
    TicketStatus,
    decide_refund,
)


class RefundOutcome(BaseModel):
    """Result of a refund request: the verdict and the ticket, if one was made."""

    model_config = ConfigDict(frozen=True)

    decision: RefundDecision
    ticket: Ticket | None


class RefundService:
    """Orchestrates policy decisions and storage for refunds."""

    def __init__(self, repo: RefundRepository, clock: Clock, settings: PolicySettings) -> None:
        self._repo = repo
        self._clock = clock
        self._settings = settings

    @property
    def clock(self) -> Clock:
        """The clock decisions are dated by."""
        return self._clock

    @property
    def settings(self) -> PolicySettings:
        """The policy numbers decisions use."""
        return self._settings

    def list_purchases(self, customer_id: UUID) -> list[Purchase]:
        """A customer's purchases."""
        return self._repo.list_purchases(customer_id)

    def list_tickets(self, customer_id: UUID) -> list[Ticket]:
        """A customer's tickets, newest first."""
        return self._repo.list_tickets(customer_id)

    def check_eligibility(self, customer_id: UUID, purchase_ids: Sequence[UUID]) -> RefundDecision:
        """Preview a decision without locking or writing.

        Read-only on purpose: it may be stale by the time a request is made,
        which is why ``request_refund`` re-decides under the lock.
        """
        return decide_refund(
            self._repo.list_purchases(customer_id),
            purchase_ids,
            self._repo.list_tickets(customer_id),
            self._clock.today(),
            self._settings,
        )

    def request_refund(self, customer_id: UUID, purchase_ids: Sequence[UUID]) -> RefundOutcome:
        """Decide and, if anything is refundable, persist a ticket atomically.

        Reading and writing inside one customer unit stops two concurrent
        requests from each passing the threshold check separately.
        """
        with self._repo.customer_unit(customer_id) as unit:
            decision = decide_refund(
                unit.purchases(),
                purchase_ids,
                unit.tickets(),
                self._clock.today(),
                self._settings,
            )
            if decision.status is None:
                return RefundOutcome(decision=decision, ticket=None)
            ticket = unit.create_ticket(
                NewTicket(
                    customer_id=customer_id,
                    status=decision.status,
                    amount_cents=decision.amount_cents,
                    purchase_ids=tuple(decision.eligible_ids),
                    decision_reasons={
                        str(i.purchase_id): i.reason
                        for i in decision.items
                        if not i.eligible and i.reason is not None
                    },
                    created_at=self._clock.now(),
                )
            )
        return RefundOutcome(decision=decision, ticket=ticket)

    def _require_staff(self, user_id: UUID) -> None:
        """Resolve the role from storage, never from the caller.

        A caller could otherwise pass a forged staff profile; an unknown user
        is denied the same way as a customer.
        """
        profile = self._repo.get_profile(user_id)
        if profile is None or profile.role is not Role.STAFF:
            raise PermissionError("only staff can review refund tickets")

    def list_pending(self, reviewer_id: UUID) -> list[Ticket]:
        """The review queue, oldest first; staff only."""
        self._require_staff(reviewer_id)
        return self._repo.list_tickets_by_status(TicketStatus.PENDING_REVIEW)

    def review(self, ticket_id: UUID, reviewer_id: UUID, approve: bool, note: str | None) -> Ticket:
        """Staff-only approve/reject of a pending ticket.

        The refund window is deliberately not re-checked: it was judged at
        request time, and review delay is not the customer's fault.
        """
        self._require_staff(reviewer_id)
        return self._repo.review_ticket(
            ticket_id,
            TicketStatus.APPROVED if approve else TicketStatus.REJECTED,
            reviewer_id,
            note,
            self._clock.now(),
        )


def build_refund_service(
    repo: RefundRepository, settings: Settings, clock: Clock | None = None
) -> RefundService:
    """Wire a ``RefundService`` from app settings.

    The default clock and the policy read the same ``settings.timezone``, so
    "today" and ticket ages can never disagree about the business day.
    """
    return RefundService(
        repo,
        clock if clock is not None else SystemClock(settings.timezone),
        PolicySettings.from_settings(settings),
    )
