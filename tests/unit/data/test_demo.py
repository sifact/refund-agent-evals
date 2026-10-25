from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from refund_agent.cli import app
from refund_agent.data import DEMO_USERS, build_demo_repository, demo_uuid, render_seed_sql
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
    assert (ROOT / "supabase" / "seed.sql").read_text() == render_seed_sql("UTC")


def test_seed_sql_dates_use_business_timezone() -> None:
    sql = render_seed_sql("Asia/Dhaka")
    assert "((now() at time zone 'Asia/Dhaka')::date - 30)" in sql
    assert "current_date" not in sql


def test_seed_sql_future_offset_renders_cleanly() -> None:
    sql = render_seed_sql("UTC")
    assert "((now() at time zone 'UTC')::date + 2)" in sql
    assert "- -" not in sql


def test_seed_sql_rejects_unknown_timezone() -> None:
    # The zone is interpolated into SQL, so only real IANA names are allowed.
    with pytest.raises(ValueError):
        render_seed_sql("UTC'; drop table purchases; --")


def test_cli_seed_sql_timezone_option() -> None:
    result = CliRunner().invoke(app, ["seed-sql", "--timezone", "Asia/Dhaka"])
    assert result.exit_code == 0, result.output
    assert result.output == render_seed_sql("Asia/Dhaka")


def test_cli_seed_sql_defaults_to_settings_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    from refund_agent.config import get_settings

    monkeypatch.setenv("TIMEZONE", "Pacific/Kiritimati")
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["seed-sql"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert result.output == render_seed_sql("Pacific/Kiritimati")
