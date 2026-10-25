# memory.py

Thread-safe in-memory `RefundRepository` used by service tests and evals.

- Implements the same contract as Postgres, so evals run fast with no database and still behave like production.
- A per-customer lock serialises units, and a store lock guards the shared dictionaries, so concurrent requests behave correctly.
- Writes are staged inside the unit and only committed on a clean exit, so an exception leaves the store untouched.
- Creating a ticket rejects any purchase already on a non-rejected ticket (across all customers), mirroring the database's unique index.
- Reviewing only works on pending tickets, and listings are ordered like the database (customer tickets newest first, review queue oldest first).
