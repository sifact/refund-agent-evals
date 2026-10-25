# clock.py

Injectable clocks, so refund rules never read the wall clock directly.

- Defines the `Clock` protocol with `today()` and a timezone-aware UTC `now()`, so the service depends on behaviour, not on a real clock.
- `FixedClock(day, timezone="UTC")` is pinned to one day, and its `now()` is noon local time in that zone (converted to UTC), so `now()` and `today()` agree on the business day even in UTC+12 or later.
- `SystemClock` computes `today()` in the configured business timezone, because "30 days ago" must follow the business's calendar, not UTC.
- `_utcnow()` is the single place that touches real time, which gives tests one seam to patch.
- Keeping time out of the rules is what lets the 30-day boundary be tested exactly.
