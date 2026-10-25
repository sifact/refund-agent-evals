# refund_service.py

`RefundService`: the only path that creates or reviews refund tickets.

- The agent tools and any API go through it, so the amount is always computed from stored prices and never accepted from a caller.
- `check_eligibility` is a read-only preview with no locking, so it may be stale; that is why it never creates anything.
- `request_refund` decides and writes inside one customer unit, so concurrent requests cannot both slip under the review threshold; it creates a ticket only when something is eligible and records declined items with their reasons.
- `review` is staff-only (otherwise `PermissionError`) and approves or rejects a pending ticket with a note.
- The refund window is deliberately not re-checked on review, because it was judged at request time and review delay is not the customer's fault; `build_refund_service(repo, settings)` wires the clock and policy from one `Settings`, so both use the same timezone.
