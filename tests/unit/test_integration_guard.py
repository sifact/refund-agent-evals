"""The integration suite truncates tables, so it must refuse non-local databases."""

import pytest

from tests.integration.db_guard import assert_local_database

LOCAL_URLS = [
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    "postgresql://postgres:postgres@localhost:54322/postgres",
    "postgresql://postgres:postgres@[::1]:54322/postgres",
    "host=127.0.0.1 port=54322 user=postgres dbname=postgres",
]
REMOTE_URLS = [
    "postgresql://u:p@db.abcd.supabase.co:5432/postgres",
    "postgresql://u:p@127.0.0.1,db.abcd.supabase.co/postgres",
    "postgresql:///postgres",  # no host at all: never assume it is safe
    "host=10.0.0.5 dbname=postgres",
]


@pytest.mark.parametrize("url", LOCAL_URLS)
def test_local_database_allowed(url: str) -> None:
    assert_local_database(url)


@pytest.mark.parametrize("url", REMOTE_URLS)
def test_non_local_database_refused(url: str) -> None:
    with pytest.raises(RuntimeError, match="non-local database"):
        assert_local_database(url)


def test_error_does_not_leak_password() -> None:
    with pytest.raises(RuntimeError) as exc:
        assert_local_database("postgresql://u:s3cret@db.abcd.supabase.co:5432/postgres")
    assert "s3cret" not in str(exc.value)
