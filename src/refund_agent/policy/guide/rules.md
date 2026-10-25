# rules.py

The single source of truth for refund eligibility: a pure `decide_refund` function.

- Pure and I/O-free: purchases, requested IDs, existing tickets, `today` and `PolicySettings` go in, a `RefundDecision` comes out, so the agent can only report a verdict and never widen it.
- Each item gets the first matching reason, in order: not owned, previously rejected, already refunded, future-dated, outside the 30-day window. Day 30 is still eligible and ownership is checked first so nothing leaks about other people's purchases.
- Duplicate requested IDs are dropped, and only eligible items add to the amount, so an item is never paid twice and declined items never reach a ticket.
- The status is `pending_review` when the running total of approved and pending tickets from the last 30 days plus this request is over the threshold (exactly $100 is approved), and `None` when nothing is eligible.
- Ticket ages are measured in the business timezone, not UTC, so tickets near local midnight cannot shift the window edge.
