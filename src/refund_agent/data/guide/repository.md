# repository.py

The storage contract: error types, the `NewTicket` write model and the repository protocols.

- `RefundRepository` and `CustomerUnit` are protocols, so the service and evals depend on behaviour and the in-memory and Postgres backends can share one contract test suite.
- `customer_unit` gives exclusive, all-or-nothing access to one customer's data, so two concurrent requests cannot each pass the review threshold separately.
- `NewTicket` only allows `approved` or `pending_review` as a starting status, because a ticket is never born rejected.
- A small error family (`TicketNotFoundError`, `DuplicateRefundError`, `InvalidTicketTransitionError`) lets callers react to storage failures without knowing the backend.
- `review_ticket` moves a pending ticket to approved or rejected and records who, when and why, which keeps the audit trail in storage.
