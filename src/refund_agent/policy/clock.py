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
    """Pinned to a day, for tests and evals that need reproducible results.

    ``now()`` is noon *local* time in ``timezone``, so ``now()`` and ``today()``
    describe the same business day; noon UTC is already tomorrow in UTC+12.
    """

    def __init__(self, day: date, timezone: str = "UTC") -> None:
        self._day = day
        self._tz = ZoneInfo(timezone)

    def today(self) -> date:
        return self._day

    def now(self) -> datetime:
        return datetime.combine(self._day, time(12), tzinfo=self._tz).astimezone(UTC)


class SystemClock:
    """Real time; 'today' is evaluated in the business timezone, not UTC."""

    def __init__(self, timezone: str) -> None:
        self._tz = ZoneInfo(timezone)

    @property
    def timezone(self) -> str:
        """The business timezone ``today()`` is evaluated in."""
        return self._tz.key

    def today(self) -> date:
        return _utcnow().astimezone(self._tz).date()

    def now(self) -> datetime:
        return _utcnow()
