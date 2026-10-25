# refund-agent-evals — Design

Date: 2026-10-26
Status: draft, awaiting approval
Reference project (read-only, never modified): `../LangChain_Agent_Evaluation_System-main/`

## 1. Intent

Rebuild the reference "LangChain refund agent + DeepEval" tutorial as a project that follows best practice from architecture to implementation to evaluation to production. The one codebase serves three uses at once:

1. **Client demo.** A polished, dark-themed product that shows a customer support agent which handles refunds safely, together with evidence (evaluation scores and traces) that it behaves correctly.
2. **Template.** Developers copy the repo to evaluate their own agents. The evaluation layer, the dataset format and the CI gate must be clearly separated from the refund-specific parts.
3. **Real service.** It can be deployed and used by real, logged-in customers. Refunds are recorded as tickets, and no money moves.

### Why the reference falls short (problems this design must fix)
- The README and the code disagree: wrong entry-point filename, a UI file that doesn't exist, and a dataset table that doesn't match the dataset.
- The evaluation reads the real clock, so expected answers expire as the calendar moves.
- Refund rules live only in the prompt. The tools accept any user and any amount, and unknown items are silently skipped.
- The customer identifies themselves by typing a username, so anyone can impersonate anyone.
- A broken metric config (`threshold=None`), no tests, flat `sys.path` imports, stale dependencies (`asyncio` from PyPI), and only one-shot single-turn evals.

## 2. Goals, non-goals, anti-goals

**Goals**
- Refund policy enforced in deterministic code that the agent cannot bypass.
- Customers are authenticated, and the agent only ever sees and acts on the logged-in customer's data.
- A layered, production-grade evaluation suite (deterministic checks, single-turn, multi-turn, policy attacks) with a CI quality gate.
- Every agent run and every evaluation score traced in Langfuse.
- Reproducible evals: a frozen clock, versioned datasets, pinned models, and thresholds recorded in config.
- A clean, reusable code layout. The docs match the code (the docs are checked in CI where feasible).

**Non-goals (for now)**
- Hosting or deployment to a cloud provider. The service must be deployable (Docker, health checks, env config), but no host is chosen.
- Real payments (Stripe or any other payment service provider).
- Multiple languages or channels (email, voice).

**Anti-goals: failure even if it "works"**
- The agent creates a refund ticket that the policy would reject, for any input, including prompt-injection attempts.
- A customer can see or refund another customer's purchases.
- Eval scores change because of the date, or because of hidden state left over from a previous run.
- Secrets end up in the public repo.
- The template is so tangled with refund logic that reusing it means rewriting the evaluation layer.

## 3. Decisions made by the user
| Area | Decision |
|---|---|
| Database & auth | **Supabase** (Postgres + Supabase Auth). Customers log in. |
| Agent model | **Groq**, a fast model |
| Judge model | **Groq**, a larger model than the agent's (one provider, one key) |
| Refund outcome | A **ticket row in Supabase**. No money moves. |
| Human approval | Refunds **over $100** become `pending_review`. Staff approve or reject them. |
| Staff review | An **admin page in the app**, visible only to staff accounts |
| UI | **Hand-written HTML + CSS** (plus minimal vanilla JS), modern **dark theme** |
| Tracing | **Langfuse** |
| Eval scope | Everything production-grade: single-turn + multi-turn + policy attacks + CI gate |
| Hosting | Skip for now |
| Repo | New **public** GitHub repo `sifact/refund-agent-evals` (GitHub account **sifact**). Every feature or fix goes on a branch and is merged through a PR. |
| Mixed requests | Ticket for the **eligible items only**; the agent explains why each other item was declined |
| Split-refund abuse | **30-day running total**: approved + pending refunds created in the last 30 days count toward the $100 review limit |
| Customer data | **Seeded demo accounts only** (customers + staff from seed data); public sign-up disabled. A purchase importer can come later. |
| Groq plan | **Free tier**: design for tight rate limits |

## 4. Decisions made by Claude (open to challenge)
- **Stack:** Python 3.12, `uv`, LangChain (`create_agent`) on LangGraph, DeepEval, FastAPI, Pydantic v2 / pydantic-settings.
- **Location:** `deepeval-langChain/refund-agent-evals/`, next to the reference folder.
- **Package:** `src/refund_agent/`, organized by stage (see §6), with a `guide/` folder of 5-bullet notes per core module.
- **Money:** stored as integer cents everywhere. Dates are `date` / `timestamptz`.
- **Window:** a purchase is eligible when `0 <= (today − purchase_date).days <= 30`. Day 30 is still eligible, and future-dated purchases are never eligible. One constant in config: `REFUND_WINDOW_DAYS = 30`.
- **Review limit:** `REVIEW_THRESHOLD_CENTS = 10000`. A new ticket goes to `pending_review` when (this ticket + the customer's approved and pending tickets created in the last 30 days) is **strictly greater than** $100. Reaching exactly $100.00 is still approved automatically.
- **Staff review timing:** the 30-day window is judged on the date the ticket was created, which is when the customer asked. Staff approval does not re-check the window.
- **Rejection is final:** a purchase on a rejected ticket can't be requested again (reason `previously_rejected`). This stops customers from asking again until a reviewer gives in.
- **Multi-turn gating:** scripted multi-turn conversations, where the user turns are fixed in YAML, gate PRs. Conversations simulated by DeepEval's simulator (the judge model plays the customer) run nightly and are reported only, not gated, because their turns differ between runs.
- **Frontend:** served by FastAPI as static files. Login uses `supabase-js` loaded from a pinned CDN URL. No frontend build step.
- **Agent memory:** the LangGraph Postgres checkpointer on the Supabase database in the service. An in-memory checkpointer for tests and evals.
- **Checks:** ruff (lint + format), mypy, pytest, pre-commit, gitleaks (secret scan), and GitHub Actions.

## 5. Architecture

```
Browser (HTML/CSS/JS, dark)
  ├─ login via Supabase Auth (supabase-js) ──► gets JWT
  └─ /api/* with Bearer JWT
        │
FastAPI (serving/)
  ├─ auth: verify Supabase JWT → CurrentUser{id, role}
  ├─ /api/chat ──► Agent (agent/) ──► Tools ──► RefundService (policy/) ──► Repository (data/) ──► Supabase Postgres
  ├─ /api/tickets (mine)
  └─ /api/admin/tickets (staff: list pending, approve, reject)
        │
Langfuse (tracing.py): every agent run, tool call, eval score
```

### 5.1 Layers and the one rule that matters
- **Policy layer (`policy/`):** pure functions, no I/O. Input: the customer's purchases, the requested purchase IDs, the customer's existing tickets, `today`, and settings. Output: a decision for each item (`eligible`, or a reason: `not_owned`, `outside_window`, `future_date`, `already_refunded`, `previously_rejected`), the total of the eligible items in cents, and the ticket status. Only eligible items go on the ticket. If none are eligible, no ticket is created. Otherwise the status is `pending_review` if the 30-day running total (§4) exceeds $100, else `approved`. This is the single source of truth for refund rules, and it is fully unit-tested.
- **Service layer:** `RefundService.create_ticket(customer_id, purchase_ids)` loads the data, calls the policy and writes the ticket in one transaction. **The amount is always computed here, never accepted from the model.** Idempotent: a purchase that is already on a non-rejected ticket can't be refunded again (enforced by both the policy and a DB constraint).
- **Agent layer:** tools are thin wrappers around the service and are **bound to the authenticated customer ID from runtime context**. No tool takes a user or customer ID, or an amount, as an argument the model controls.
- **Clock:** a `Clock` protocol (`SystemClock`, `FixedClock`). The agent gets today's date from it, and evals use `FixedClock`.

### 5.2 Data model (Supabase migrations in `supabase/migrations/`)
- `profiles(id uuid pk → auth.users, display_name, role text check in ('customer','staff'))`
- `purchases(id uuid pk, customer_id → profiles, item_name, price_cents int > 0, purchased_on date)`
- `refund_tickets(id uuid pk, customer_id, status check in ('approved','pending_review','rejected'), amount_cents, decision_reasons jsonb, created_at, reviewed_by null, reviewed_at null, review_note null)`
- `refund_ticket_items(ticket_id, purchase_id, unique purchase_id among non-rejected tickets)`: blocks double refunds.
- **RLS on every table.** Customers can `select` only their own rows. Staff can `select` all rows. No client-side writes: all writes go through the API server (service role), after the policy runs.
- `supabase/seed.sql` contains demo customers, a staff user and purchases, with dates relative to a documented demo date.
- **Accounts:** public sign-up is disabled in the Supabase auth config. The seeded demo customers and staff are the only accounts. Demo login credentials are documented in the README and are clearly fake. `profiles.role` is set only by seed or migration, never from the client.

### 5.3 Agent
- LangChain `create_agent` with a Groq chat model, plus a system prompt that explains the policy in customer-friendly terms. The code enforces the policy anyway.
- Tools: `list_my_purchases()`, `check_refund_eligibility(purchase_ids)`, `create_refund_ticket(purchase_ids)`, `get_my_tickets()`. Today's date is provided through the prompt or context from `Clock`, not a separate tool call.
- Structured output: `AgentReply{message: str, state: 'needs_input'|'resolved', ticket_id: str|None}`.
- Guardrails: a recursion/step limit, a request timeout, the max message length and per-user rate limiting at the API. Model output never decides money.

### 5.4 API and UI
- `POST /api/chat {session_id?, message}` → `AgentReply` (streaming is optional, builder's call).
- `GET /api/tickets`. `GET /api/admin/tickets?status=pending_review`. `POST /api/admin/tickets/{id}/approve|reject {note}` (staff only, server-side role check, audit fields set; only `pending_review` tickets can change, and the window is not re-checked).
- `GET /healthz` (liveness) and `GET /readyz` (DB + model config reachable).
- Pages: login, chat (with "my purchases" and "my tickets" panels), admin review. Dark theme with CSS custom properties, responsive, accessible (contrast, focus states, keyboard use).
- Errors use one JSON error shape and never leak stack traces or secrets.

### 5.5 Observability
- The Langfuse callback handler is attached to every agent invocation, tagged with `user_id`, `session_id`, the app version and the model IDs.
- Structured JSON logs with a request ID. Logs never contain PII beyond the user ID.
- Eval runs push scores to Langfuse as a dataset run, so prompt and model changes can be compared over time.

## 6. Repository layout

```
refund-agent-evals/
  src/refund_agent/
    config.py            # pydantic-settings: all env vars, thresholds, model IDs
    logging.py
    tracing.py           # Langfuse setup
    cli.py               # `refund-agent serve | eval ... | seed`
    policy/              # pure refund rules, Clock      + guide/
    data/                # Repository protocol, Supabase + in-memory impls, schemas  + guide/
    agent/               # prompt, tools, builder, response schema  + guide/
    evaluation/          # dataset loading, harness, metrics, runners, gate, reporting  + guide/
    serving/             # FastAPI app, routes, auth, static/ (html, css, js)
  evals/
    datasets/            # versioned YAML: single_turn, multi_turn, adversarial
    thresholds.yaml      # gate thresholds per metric and per suite
  supabase/              # config.toml, migrations/, seed.sql
  tests/unit/  tests/integration/  tests/e2e/
  docs/                  # README links, architecture, superpowers specs/plans
  .github/workflows/     # ci.yml, eval.yml, nightly-eval.yml
  Dockerfile  docker-compose.yml  .env.example  pyproject.toml  uv.lock
```
`evaluation/` must not import from `agent/`, `policy/` or `data/` directly. It talks to an `AgentUnderTest` protocol, with a refund adapter as the one concrete implementation. That keeps the template reusable.

## 7. Evaluation strategy

### 7.1 Layers (cheapest first)
1. **Deterministic tests, with no keys (pytest, every push):** the policy rules (boundaries: day 0, 30, 31, future, $100.00 versus $100.01, already refunded, not owned), the service transaction and idempotency, tool binding (tools can't reach another customer), API auth and roles, and RLS (an integration test against local Supabase).
2. **Outcome assertions on agent runs (code-graded, no judge):** after each eval case, check the resulting **database state** against the golden's expected outcome: ticket created or not, exact amount in cents, status, which purchase IDs. This is the primary pass/fail signal.
3. **Single-turn goldens (DeepEval):** `ToolCorrectnessMetric` (names + key args), `ArgumentCorrectnessMetric`, `TaskCompletionMetric`, `StepEfficiencyMetric`, and a `GEval` for answer correctness and clarity of the policy explanation. `PlanQuality`/`PlanAdherence` are reported but not gated (the reference showed they're noisy for this agent).
4. **Multi-turn conversations:** the customer omits details, changes their mind, or asks follow-ups. **Scripted** conversational goldens (fixed user turns) gate PRs. **Simulated** conversations (DeepEval simulator, with the judge model playing the customer) run nightly and are reported only. Metrics: conversation completeness, knowledge retention, role adherence, plus the outcome assertions on the final DB state.
5. **Policy attacks (adversarial goldens):** "ignore the 30-day rule", inventing items, asking for another customer's refund, inflated amounts, prompt injection inside item names, splitting a >$100 refund across tickets (the second ticket must be `pending_review`), and asking again for a rejected purchase. The gate is **zero policy violations** (layer 2 assertions), with no score averaging.

### 7.2 Dataset
- YAML in `evals/datasets/`, versioned in git. Each case has: `id`, `suite`, `customer` (a seeded customer), `turns` or `input`, `expected_outcome` (ticket / no ticket, amount_cents, status, purchase IDs), `expected_tools`, `tags`.
- Each case runs against a **fresh in-memory repository** seeded from a fixture, with `FixedClock(EVAL_DATE)`. No shared state between cases, and no network apart from the models and Langfuse.
- Coverage targets: at least 30 single-turn cases, 10 multi-turn and 15 adversarial at launch, including every boundary in 7.1.1.

### 7.3 Reliability
- Pinned agent and judge model IDs in config, temperature 0 where supported, and judge caching off.
- Each case runs `n` times (PR: 1, nightly: 3). The report shows the pass rate per case so flaky cases are visible.
- Thresholds live in `evals/thresholds.yaml`, not in code.

### 7.3a Groq free-tier budget
- Concurrency and the requests-per-minute rate come from config (default: low, e.g. 1–2 concurrent cases). Model calls retry with exponential backoff and honor `retry-after` on 429 responses.
- **PR eval runs a tagged `pr` subset:** every adversarial case, the boundary cases and a few happy paths. Its run time and token use are kept under the free-tier daily limits. The **full suite runs nightly**. If the nightly `n=3` exceeds the limit, `n` and the suite size are set in config, and the report records which values were used.
- The run fails clearly with "rate-limited, incomplete" when it couldn't finish, rather than reporting partial scores as a pass.

### 7.4 CI gate
- `ci.yml` (every PR/push, no secrets needed): lint, typecheck, unit tests, integration tests against local Supabase, secret scan and Docker build.
- `eval.yml` (PRs that touch `src/refund_agent/{agent,policy}`, `evals/`, or prompts; uses repo secrets): run the eval suites, fail the PR if any adversarial case violates policy, any outcome assertion drops below threshold, or any gated metric drops below its threshold. Post a markdown summary as a PR comment and upload the full report as an artifact.
- `nightly-eval.yml`: the full suite with `n=3`. Results go to Langfuse.
- Fork PRs (public repo) don't get secrets, so `eval.yml` skips with a clear message. A maintainer reruns it.

## 8. Engineering workflow
- `main` is protected. Every feature or fix goes on a branch, then a PR, then CI green, then a squash merge. Commit messages follow Conventional Commits.
- No Claude or AI attribution in commits or PRs (user instruction).
- Pre-commit runs ruff, mypy (on changed files), gitleaks and end-of-file fixers.
- Secrets live only in `.env` (gitignored) and GitHub Actions secrets. `.env.example` lists every variable.
- README: what it is, a screenshot, quick start (local Supabase + `uv run refund-agent serve`), how to run evals, how to adapt the template, and the architecture. Every command in the README is exercised in CI or by a smoke test.

## 9. Constraints
- Public repo: no secrets, no real customer data. The seed data is fictional.
- Groq only, for both agent and judge. The chosen models must support tool calling and structured output.
- The reference folder must not be modified.
- The user's global rules apply: stage-based package layout, a `guide/` folder per core sub-package, config in one place, seeds/frozen clock for reproducibility, and verifying behavior after any restructure.

## 10. Left to the builder
- The exact Groq model IDs (pick current, tool-calling-capable models from Groq's live model list; the judge must be larger than the agent model).
- Whether `/api/chat` streams.
- Exact visual design within "modern dark theme, hand-written HTML/CSS".
- The rate-limiting implementation, and JWT verification details (JWKS or a shared secret, depending on the Supabase project settings).
- Docker Compose specifics for local development.
- Whether to use `deepteam` for extra red-team generation on top of the hand-written adversarial goldens.
