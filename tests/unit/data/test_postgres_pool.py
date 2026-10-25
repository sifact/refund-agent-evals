"""``make_pool`` must fail fast and clearly when no database is configured."""

import pytest

from refund_agent.config import Settings
from refund_agent.data import make_pool


def test_make_pool_requires_database_url() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        make_pool(Settings(_env_file=None, database_url=None))
