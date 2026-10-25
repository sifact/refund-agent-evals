"""Run the shared repository contract against the in-memory implementation."""

from collections.abc import Iterable

from refund_agent.data import InMemoryRepository, RefundRepository
from refund_agent.policy import Profile, Purchase, Ticket
from tests.contract.repository_contract import RepositoryContract


class TestInMemory(RepositoryContract):
    """The in-memory repository must satisfy the same contract as Postgres."""

    def make_repo(
        self,
        *,
        profiles: Iterable[Profile],
        purchases: Iterable[Purchase],
        tickets: Iterable[Ticket],
    ) -> RefundRepository:
        return InMemoryRepository(profiles, purchases, tickets)
