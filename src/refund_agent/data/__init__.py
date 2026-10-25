"""Persistence layer: the repository protocol and its implementations."""

from refund_agent.data.demo import (
    DEMO_EMAIL_DOMAIN,
    DEMO_PASSWORD,
    DEMO_USERS,
    DemoPurchase,
    DemoUser,
    build_demo_repository,
    demo_uuid,
)
from refund_agent.data.memory import InMemoryRepository
from refund_agent.data.postgres import PostgresRepository, make_pool
from refund_agent.data.repository import (
    CustomerUnit,
    DuplicateRefundError,
    InvalidTicketTransitionError,
    NewTicket,
    RefundRepository,
    RepositoryError,
    TicketNotFoundError,
)
from refund_agent.data.seed_sql import render_seed_sql

__all__ = [
    "DEMO_EMAIL_DOMAIN",
    "DEMO_PASSWORD",
    "DEMO_USERS",
    "CustomerUnit",
    "DemoPurchase",
    "DemoUser",
    "DuplicateRefundError",
    "InMemoryRepository",
    "InvalidTicketTransitionError",
    "NewTicket",
    "PostgresRepository",
    "RefundRepository",
    "RepositoryError",
    "TicketNotFoundError",
    "build_demo_repository",
    "demo_uuid",
    "make_pool",
    "render_seed_sql",
]
