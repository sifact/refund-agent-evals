"""Persistence layer: the repository protocol and its implementations."""

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

__all__ = [
    "CustomerUnit",
    "DuplicateRefundError",
    "InMemoryRepository",
    "InvalidTicketTransitionError",
    "NewTicket",
    "PostgresRepository",
    "RefundRepository",
    "RepositoryError",
    "TicketNotFoundError",
    "make_pool",
]
