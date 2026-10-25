# postgres.py

The Postgres (Supabase) `RefundRepository`, built on a psycopg connection pool.

- Guarantees live in the database: a `SELECT ... FOR UPDATE` on the customer's profile row serialises that customer's requests, so they hold for every process and replica.
- The partial unique index `refund_ticket_items_active_purchase_uq` makes a double refund impossible even if the lock were bypassed, and a clash is translated into `DuplicateRefundError`.
- Ticket creation runs in a savepoint and on the unit's own connection, so a clash undoes only that ticket and staged tickets are visible to the unit but not to others.
- Review is one guarded `UPDATE ... WHERE status = 'pending_review'`, so two reviewers racing cannot both win; rejecting also frees the ticket's items in the same transaction.
- It connects as the table owner (bypassing row-level security, which exists for browser clients), and `make_pool` fails fast when `DATABASE_URL` is not set.
