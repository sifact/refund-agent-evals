# demo.py

Declarative demo data: one staff user and eight customers, each showing one scenario.

- `DEMO_USERS` lists accounts on `@demo.refund-agent.dev` with the fake password `demo-password-123`, for local and demo databases only.
- Purchases are stored as `days_ago` (negative means future-dated), so the same table feeds the SQL seed and in-memory evals and the 30-day boundary never goes stale.
- `demo_uuid` derives deterministic IDs, so the SQL seed, evals and tests agree on identities.
- The scenarios cover the boundaries: today (alice), day 30 and day 31 (bob and carol), a future date (dave), over $100 (erin), two items totalling $120 (frank), mixed eligible and old items (grace) and no purchases (heidi).
- `build_demo_repository(today)` builds the same data in memory against a given date, for evals with a fixed clock.
