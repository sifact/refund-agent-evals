"""Injectable clocks so policy rules stay deterministic under test."""

from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    """Source of the current date and time."""

    def today(self) -> date: ...

    def now(self) -> datetime:
        """Timezone-aware UTC timestamp."""
        ...


def _utcnow() -> datetime:
    """Single seam for wall-clock access, patched in tests."""
    return datetime.now(UTC)


class FixedClock:
    """Pinned to a day, for tests and evals that need reproducible results."""

    def __init__(self, day: date) -> None:
        self._day = day

    def today(self) -> date:
        return self._day

    def now(self) -> datetime:
        return datetime.combine(self._day, time(12), tzinfo=UTC)


class SystemClock:
    """Real time; 'today' is evaluated in the business timezone, not UTC."""

    def __init__(self, timezone: str) -> None:
        self._tz = ZoneInfo(timezone)

    def today(self) -> date:
        return _utcnow().astimezone(self._tz).date()

    def now(self) -> datetime:
        return _utcnow()
