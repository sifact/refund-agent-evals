# refund-agent-evals

A production-grade refund support agent, with a layered DeepEval evaluation suite.

## What it is for

1. **A working refund agent.** Customers ask for refunds in chat; the agent can only report what the policy code decides.
2. **A way to prove it behaves.** Cheap deterministic checks first, then model-graded and adversarial tests, gated in CI.
3. **A template.** Copy it to evaluate your own agent. The evaluation layer is kept separate from the refund-specific parts.

## Status

| Plan | Scope | State |
|---|---|---|
| 1. Foundation | Policy rules, storage (in-memory and Postgres), refund service, demo data | Done |
| 2. Agent and tracing | LangChain refund agent on Groq, its tools and Langfuse tracing | Planned |
| 3. Evaluation and CI gate | Deterministic, single-turn, multi-turn and policy-attack evals, gated in CI | Planned |
| 4. API, auth and UI | FastAPI routes, Supabase login and the dark-theme HTML chat UI | Planned |
| 5. Production hardening | Guardrails, rate limiting and deployment readiness | Planned |

See the [design spec](docs/superpowers/specs/2026-10-26-refund-agent-evals-design.md) and the [Foundation plan](docs/superpowers/plans/2026-10-26-01-foundation.md).

## Refund rules

| Rule | Behaviour |
|---|---|
| Refund window | 30 days from purchase, inclusive (day 30 is eligible, day 31 is not). Future-dated purchases are never eligible. |
| What goes on a ticket | Only eligible items. If none are eligible, no ticket is created. |
| Review | A ticket goes to `pending_review` when the 30-day running total of approved and pending tickets, plus this ticket, is over $100. Exactly $100 is auto-approved. |
| Running total | Ticket ages use the business timezone (`TIMEZONE`, default `UTC`). A ticket dated after today still counts, so the check fails closed. |
| Rejection | Final. A rejected purchase cannot be requested again (`previously_rejected`). |
| Staff approval | Does not re-check the window; it was judged at request time. |

The numbers are configurable in `src/refund_agent/config.py` (env vars `REFUND_WINDOW_DAYS`, `REVIEW_THRESHOLD_CENTS`, `RUNNING_TOTAL_DAYS`, `TIMEZONE`).

## Local setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), the [Supabase CLI](https://supabase.com/docs/guides/local-development) and Docker (Colima works) for the local Supabase stack.

```bash
git clone https://github.com/sifact/refund-agent-evals.git
cd refund-agent-evals
cp .env.example .env           # local defaults; edit TIMEZONE and friends here
uv sync
supabase start
supabase db reset              # applies migrations and loads the demo seed; run before every demo
uv run pytest                  # unit tests (no database needed)
uv run pytest -m integration   # database tests (needs local Supabase)
```

Integration tests read `TEST_DATABASE_URL` (default `postgresql://postgres:postgres@127.0.0.1:54322/postgres`) and refuse to run against non-local hosts, because they wipe the app tables. That includes the local demo data: run `supabase db reset` afterwards to restore it.

Seed purchase dates are relative to today in the business timezone (`TIMEZONE`), not the database session's `current_date`. The committed `supabase/seed.sql` is rendered for UTC; regenerate it from the demo data with:

```bash
uv run refund-agent seed-sql --timezone UTC > supabase/seed.sql   # omit --timezone to use TIMEZONE from .env
```

## Demo accounts

All accounts are on `@demo.refund-agent.dev` and share the fake password `demo-password-123`. Use them on local or demo databases only.

| Account | Scenario |
|---|---|
| `staff@` | Staff reviewer (Sam Staff); approves or rejects pending tickets |
| `alice@` | One $45 purchase made today; a simple approval |
| `bob@` | $25 purchase exactly 30 days old; still eligible |
| `carol@` | $80 purchase 31 days old; outside the window |
| `dave@` | $30 purchase dated two days in the future; never eligible |
| `erin@` | One $129 purchase 5 days old; over $100, goes to review |
| `frank@` | Two $60 purchases (total $120); over $100, goes to review |
| `grace@` | A recent $45 purchase and a 45-day-old $30 one; mixed eligibility |
| `heidi@` | No purchases; nothing to refund |

## Project layout

```
src/refund_agent/
  policy/    models, clocks and the pure eligibility rules
  data/      repository contract, in-memory and Postgres backends, demo data
  service/   RefundService, the only way to create or review tickets
supabase/    migrations and the generated seed
tests/       unit, contract and integration tests
```

Each core module has a short guide in its package's `guide/` folder.
