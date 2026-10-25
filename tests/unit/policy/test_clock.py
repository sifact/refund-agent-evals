"""Tests for the injectable clocks."""

from datetime import UTC, date, datetime
from unittest.mock import patch

from refund_agent.policy import FixedClock, SystemClock


def test_fixed_clock() -> None:
    clock = FixedClock(date(2026, 10, 15))
    assert clock.today() == date(2026, 10, 15)
    assert clock.now().tzinfo is not None


def test_system_clock_uses_configured_timezone() -> None:
    late = datetime(2026, 10, 15, 23, 30, tzinfo=UTC)
    with patch("refund_agent.policy.clock._utcnow", return_value=late):
        assert SystemClock("UTC").today() == date(2026, 10, 15)
        assert SystemClock("Asia/Dhaka").today() == date(2026, 10, 16)


def test_fixed_clock_now_is_local_noon() -> None:
    from zoneinfo import ZoneInfo

    day = date(2026, 10, 15)
    utc_clock = FixedClock(day)
    assert utc_clock.now() == datetime(2026, 10, 15, 12, tzinfo=UTC)
    kiri = FixedClock(day, "Pacific/Kiritimati")
    local = kiri.now().astimezone(ZoneInfo("Pacific/Kiritimati"))
    assert (local.date(), local.hour) == (day, 12)
    assert kiri.now().utcoffset() == UTC.utcoffset(None)
    assert kiri.today() == day
