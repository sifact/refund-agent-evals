"""Backend-agnostic contract for ``RefundRepository`` implementations.

Why a mixin: the in-memory and Postgres repositories must behave identically,
so both subclass this and only supply ``make_repo``. The name deliberately does
not start with ``Test`` so pytest only collects the concrete subclasses.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from refund_agent.data import (
    DuplicateRefundError,
    InvalidTicketTransitionError,
    NewTicket,
    RefundRepository,
    TicketNotFoundError,
)
from refund_agent.policy import Profile, Purchase, Role, Ticket, TicketStatus

CUSTOMER = UUID("00000000-0000-0000-0000-0000000000c1")
OTHER = UUID("00000000-0000-0000-0000-0000000000c2")
STAFF = UUID("00000000-0000-0000-0000-0000000000a1")

C_P1 = UUID("00000000-0000-0000-0000-00000000c001")
C_P2 = UUID("00000000-0000-0000-0000-00000000c002")
O_P1 = UUID("00000000-0000-0000-0000-00000000d001")
O_P2 = UUID("00000000-0000-0000-0000-00000000d002")

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 1, 3, 9, 0, tzinfo=UTC)

PROFILES = [
    Profile(id=CUSTOMER, display_name="Casey", role=Role.CUSTOMER),
    Profile(id=OTHER, display_name="Otto", role=Role.CUSTOMER),
    Profile(id=STAFF, display_name="Sam", role=Role.STAFF),
]
PURCHASES = [
    Purchase(
        id=C_P1,
        customer_id=CUSTOMER,
        item_name="Lamp",
        price_cents=1000,
        purchased_on=date(2026, 1, 1),
    ),
    Purchase(
        id=C_P2,
        customer_id=CUSTOMER,
        item_name="Desk",
        price_cents=2000,
        purchased_on=date(2026, 1, 1),
    ),
    Purchase(
        id=O_P1,
        customer_id=OTHER,
        item_name="Chair",
        price_cents=3000,
        purchased_on=date(2026, 1, 1),
    ),
    Purchase(
        id=O_P2,
        customer_id=OTHER,
        item_name="Rug",
        price_cents=4000,
        purchased_on=date(2026, 1, 1),
    ),
]


def new_ticket(
    purchase_ids: tuple[UUID, ...],
    *,
    created_at: datetime = T0,
    status: TicketStatus = TicketStatus.PENDING_REVIEW,
    amount_cents: int = 1000,
) -> NewTicket:
    """Build a ``NewTicket`` for ``CUSTOMER`` with sensible defaults."""
    return NewTicket(
        customer_id=CUSTOMER,
        status=status,
        amount_cents=amount_cents,
        purchase_ids=purchase_ids,
        decision_reasons={},
        created_at=created_at,
    )


class RepositoryContract:
    """Behaviour every ``RefundRepository`` must satisfy."""

    def make_repo(
        self,
        *,
        profiles: Iterable[Profile],
        purchases: Iterable[Purchase],
        tickets: Iterable[Ticket],
    ) -> RefundRepository:
        """Return a fresh repository seeded with the given rows."""
        raise NotImplementedError

    def _repo(self, tickets: Iterable[Ticket] = ()) -> RefundRepository:
        return self.make_repo(profiles=PROFILES, purchases=PURCHASES, tickets=tickets)

    def _create(self, repo: RefundRepository, nt: NewTicket) -> Ticket:
        with repo.customer_unit(nt.customer_id) as unit:
            return unit.create_ticket(nt)

    def _create_in(self, repo: RefundRepository, customer_id: UUID, nt: NewTicket) -> Ticket:
        with repo.customer_unit(customer_id) as unit:
            return unit.create_ticket(nt)

    def test_list_purchases_scoped_to_customer(self) -> None:
        repo = self._repo()
        assert {p.id for p in repo.list_purchases(CUSTOMER)} == {C_P1, C_P2}
        assert {p.id for p in repo.list_purchases(OTHER)} == {O_P1, O_P2}

    def test_create_and_list_ticket(self) -> None:
        repo = self._repo()
        first = self._create(repo, new_ticket((C_P1,), created_at=T0))
        second = self._create(repo, new_ticket((C_P2,), created_at=T1))
        assert first.id != second.id
        assert first.status is TicketStatus.PENDING_REVIEW
        assert first.purchase_ids == (C_P1,)
        assert [t.id for t in repo.list_tickets(CUSTOMER)] == [second.id, first.id]
        assert repo.get_ticket(first.id) == first
        assert repo.list_tickets(OTHER) == []

    def test_duplicate_refund_rejected(self) -> None:
        repo = self._repo()
        self._create(repo, new_ticket((C_P1,)))
        with pytest.raises(DuplicateRefundError):
            self._create(repo, new_ticket((C_P1, C_P2), created_at=T1))
        assert len(repo.list_tickets(CUSTOMER)) == 1

    def test_rejected_purchase_can_be_on_new_ticket_at_storage_level(self) -> None:
        # Storage frees rejected purchases; the policy layer is what blocks a
        # re-request. Pinning the split keeps both backends honest.
        repo = self._repo()
        ticket = self._create(repo, new_ticket((C_P1,)))
        repo.review_ticket(ticket.id, TicketStatus.REJECTED, STAFF, "no", T1)
        again = self._create(repo, new_ticket((C_P1,), created_at=T2))
        assert again.purchase_ids == (C_P1,)

    def test_new_ticket_rejects_duplicate_purchase_ids(self) -> None:
        # Without this, Postgres fails on the (ticket_id, purchase_id) primary
        # key while memory would silently store the repeat: a backend split.
        repo = self._repo()
        with pytest.raises(ValueError, match="duplicate"):
            new_ticket((C_P1, C_P1))
        assert repo.list_tickets(CUSTOMER) == []

    def test_unit_rolls_back_on_exception(self) -> None:
        repo = self._repo()
        with pytest.raises(RuntimeError), repo.customer_unit(CUSTOMER) as unit:
            unit.create_ticket(new_ticket((C_P1,)))
            raise RuntimeError("boom")
        assert repo.list_tickets(CUSTOMER) == []

    def test_create_ticket_for_other_customer_rejected(self) -> None:
        repo = self._repo()
        foreign = NewTicket(
            customer_id=OTHER,
            status=TicketStatus.APPROVED,
            amount_cents=3000,
            purchase_ids=(O_P1,),
            decision_reasons={},
            created_at=T0,
        )
        with pytest.raises(ValueError):
            self._create_in(repo, CUSTOMER, foreign)
        assert repo.list_tickets(OTHER) == []

    def test_duplicate_check_is_global(self) -> None:
        seeded = Ticket(
            id=UUID("00000000-0000-0000-0000-00000000bb01"),
            customer_id=OTHER,
            status=TicketStatus.APPROVED,
            amount_cents=3000,
            purchase_ids=(O_P1,),
            decision_reasons={},
            created_at=T0,
        )
        repo = self._repo([seeded])
        again = NewTicket(
            customer_id=OTHER,
            status=TicketStatus.APPROVED,
            amount_cents=3000,
            purchase_ids=(O_P1,),
            decision_reasons={},
            created_at=T1,
        )
        with pytest.raises(DuplicateRefundError):
            self._create_in(repo, OTHER, again)
        assert repo.list_tickets(OTHER) == [seeded]

    def test_unit_writes_hidden_until_exit(self) -> None:
        repo = self._repo()
        with repo.customer_unit(CUSTOMER) as unit:
            created = unit.create_ticket(new_ticket((C_P1,)))
            assert repo.list_tickets(CUSTOMER) == []
            assert [t.id for t in unit.tickets()] == [created.id]
        assert [t.id for t in repo.list_tickets(CUSTOMER)] == [created.id]

    def test_review_pending_to_approved(self) -> None:
        repo = self._repo()
        ticket = self._create(repo, new_ticket((C_P1,)))
        reviewed = repo.review_ticket(ticket.id, TicketStatus.APPROVED, STAFF, "ok", T1)
        assert reviewed.status is TicketStatus.APPROVED
        assert reviewed.reviewed_by == STAFF
        assert reviewed.reviewed_at == T1
        assert reviewed.review_note == "ok"
        assert repo.get_ticket(ticket.id) == reviewed

    def test_review_non_pending_raises_invalid_transition(self) -> None:
        repo = self._repo()
        ticket = self._create(repo, new_ticket((C_P1,), status=TicketStatus.APPROVED))
        with pytest.raises(InvalidTicketTransitionError):
            repo.review_ticket(ticket.id, TicketStatus.REJECTED, STAFF, None, T1)

    def test_review_unknown_ticket_raises_not_found(self) -> None:
        repo = self._repo()
        missing = UUID("00000000-0000-0000-0000-00000000ffff")
        with pytest.raises(TicketNotFoundError):
            repo.review_ticket(missing, TicketStatus.APPROVED, STAFF, None, T1)

    def test_list_tickets_by_status_oldest_first(self) -> None:
        repo = self._repo()
        late = self._create(repo, new_ticket((C_P1,), created_at=T2))
        early = self._create(repo, new_ticket((C_P2,), created_at=T0))
        done = self._create(
            repo,
            NewTicket(
                customer_id=OTHER,
                status=TicketStatus.APPROVED,
                amount_cents=3000,
                purchase_ids=(O_P1,),
                decision_reasons={},
                created_at=T1,
            ),
        )
        pending = repo.list_tickets_by_status(TicketStatus.PENDING_REVIEW)
        assert [t.id for t in pending] == [early.id, late.id]
        assert [t.id for t in repo.list_tickets_by_status(TicketStatus.APPROVED)] == [done.id]

    def test_get_profile_role(self) -> None:
        repo = self._repo()
        profile = repo.get_profile(STAFF)
        assert profile is not None
        assert profile.role is Role.STAFF
        assert repo.get_profile(UUID(int=0)) is None
