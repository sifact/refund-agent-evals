from datetime import date
from pathlib import Path

from refund_agent.data.demo import DEMO_USERS, build_demo_repository, demo_uuid
from refund_agent.data.seed_sql import render_seed_sql
from refund_agent.policy import Role

ROOT = Path(__file__).resolve().parents[3]


def test_demo_ids_deterministic() -> None:
    assert demo_uuid("user", "alice") == demo_uuid("user", "alice")
    assert demo_uuid("user", "alice") != demo_uuid("user", "bob")


def test_demo_covers_boundaries() -> None:
    purchases = [p for u in DEMO_USERS for p in u.purchases]
    assert {0, 30, 31, -2} <= {p.days_ago for p in purchases}
    assert any(p.price_cents > 10000 for p in purchases)
    assert sum(u.role is Role.STAFF for u in DEMO_USERS) == 1
    assert sum(u.role is Role.CUSTOMER for u in DEMO_USERS) >= 8
    assert any(not u.purchases for u in DEMO_USERS)
    assert all(u.email.endswith("@demo.refund-agent.dev") for u in DEMO_USERS)


def test_build_demo_repository_relative_dates() -> None:
    repo = build_demo_repository(date(2026, 10, 15))
    dates = {
        p.purchased_on for u in DEMO_USERS for p in repo.list_purchases(demo_uuid("user", u.key))
    }
    assert date(2026, 9, 15) in dates
    assert date(2026, 10, 15) in dates


def test_seed_sql_is_committed_and_current() -> None:
    assert (ROOT / "supabase" / "seed.sql").read_text() == render_seed_sql()
