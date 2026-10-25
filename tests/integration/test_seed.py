"""The demo seed applies to a real local Supabase and matches the declared data.

Order independence: the autouse ``clean_db`` (conftest) truncates app tables
before every test, so the module fixture below runs after it for each test
(function scope) and re-applies the seed from scratch.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest

from refund_agent.data import DEMO_EMAIL_DOMAIN, DEMO_USERS, demo_uuid, render_seed_sql
from tests.integration.conftest import APP_TABLES

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def seeded(clean_db: None, conn: psycopg.Connection[Any]) -> None:
    """Depends on ``clean_db`` so it always runs after it, then re-seeds."""
    conn.execute(f"truncate {APP_TABLES} cascade")
    conn.execute("delete from auth.users where email like %s", (f"%@{DEMO_EMAIL_DOMAIN}",))
    conn.execute(render_seed_sql())  # type: ignore[arg-type]


def _count(conn: psycopg.Connection[Any], table: str) -> int:
    row = conn.execute(f"select count(*) from {table}").fetchone()  # type: ignore[call-overload]
    assert row is not None
    return int(row[0])


def test_seed_applies(conn: psycopg.Connection[Any]) -> None:
    assert _count(conn, "profiles") == len(DEMO_USERS)
    assert _count(conn, "purchases") == sum(len(u.purchases) for u in DEMO_USERS)
    assert _count(conn, "auth.identities where provider = 'email'") >= len(DEMO_USERS)
    staff = conn.execute("select count(*) from profiles where role = 'staff'").fetchone()
    assert staff == (1,)


def test_seed_is_idempotent(conn: psycopg.Connection[Any]) -> None:
    conn.execute(render_seed_sql())  # type: ignore[arg-type]
    assert _count(conn, "profiles") == len(DEMO_USERS)


def test_seed_dates_follow_business_timezone(conn: psycopg.Connection[Any]) -> None:
    # UTC+14 is a different calendar day from UTC for half of every day, so
    # this catches a seed that dated purchases by the database's own zone.
    zone = "Pacific/Kiritimati"
    conn.execute(f"truncate {APP_TABLES} cascade")
    conn.execute(render_seed_sql(zone))  # type: ignore[arg-type]
    today = datetime.now(UTC).astimezone(ZoneInfo(zone)).date()
    expected = {
        demo_uuid("purchase", u.key, str(i)): today - timedelta(days=p.days_ago)
        for u in DEMO_USERS
        for i, p in enumerate(u.purchases)
    }
    rows = conn.execute("select id, purchased_on from purchases").fetchall()
    assert dict(rows) == expected
