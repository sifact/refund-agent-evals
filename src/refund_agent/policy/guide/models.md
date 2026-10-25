# models.py

Frozen domain types shared by the policy, service and storage layers.

- Defines the enums `Role`, `TicketStatus` (approved, pending_review, rejected) and `DeclineReason` (not_owned, outside_window, future_date, already_refunded, previously_rejected), so statuses and reasons are never loose strings.
- Every model inherits a frozen base, so a decision cannot be altered on its way to the database or audit log.
- `Purchase.price_cents` must be positive, so a refund is never free, and `Ticket.created_at` must be timezone-aware, so ticket ages are never ambiguous.
- `ItemDecision` validates itself: an eligible item has no reason and a declined item must have one, which keeps verdicts consistent.
- `RefundDecision` carries one verdict per requested item plus the total and the proposed status (`None` when nothing is refundable), and exposes `eligible_ids` for building the ticket.
