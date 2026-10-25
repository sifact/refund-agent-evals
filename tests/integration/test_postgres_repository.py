"""Run the shared repository contract against the real Postgres schema."""

from collections.abc import Iterable

import pytest
from psycopg_pool import ConnectionPool

from refund_agent.data import PostgresRepository, RefundRepository
from refund_agent.policy import Profile, Purchase, Ticket
from tests.contract.repository_contract import RepositoryContract
from tests.integration.conftest import Seeder

pytestmark = pytest.mark.integration


class TestPostgres(RepositoryContract):
    """Postgres must behave exactly like the in-memory reference."""

    @pytest.fixture(autouse=True)
    def _bind(self, pool: ConnectionPool, seed: Seeder) -> None:
        self._pool = pool
        self._seed = seed

    def make_repo(
        self,
        *,
        profiles: Iterable[Profile],
        purchases: Iterable[Purchase],
        tickets: Iterable[Ticket],
    ) -> RefundRepository:
        self._seed(profiles, purchases, tickets)
        return PostgresRepository(self._pool)
