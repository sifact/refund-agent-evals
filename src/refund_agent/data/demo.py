"""Declarative demo data: who exists and what they bought.

Why relative days: purchases are stored as ``days_ago`` so the same table drives
both the SQL seed (``current_date - n``) and the in-memory evals (a fixed
clock), and the 30-day refund window boundaries never go stale.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from refund_agent.data.memory import InMemoryRepository
from refund_agent.policy import Profile, Purchase, Role

DEMO_PASSWORD = "demo-password-123"  # clearly fake; local/demo databases only
DEMO_EMAIL_DOMAIN = "demo.refund-agent.dev"
_NAMESPACE = uuid5(NAMESPACE_URL, "https://demo.refund-agent.dev/")


@dataclass(frozen=True)
class DemoPurchase:
    item_name: str
    price_cents: int
    days_ago: int  # negative = future-dated (invalid) purchase


@dataclass(frozen=True)
class DemoUser:
    key: str
    email: str
    display_name: str
    role: Role
    purchases: tuple[DemoPurchase, ...] = ()


def demo_uuid(*parts: str) -> UUID:
    """Deterministic ID so the SQL seed, evals and tests all agree on identities."""
    return uuid5(_NAMESPACE, "/".join(parts))


def _customer(key: str, name: str, *purchases: DemoPurchase) -> DemoUser:
    return DemoUser(key, f"{key}@{DEMO_EMAIL_DOMAIN}", name, Role.CUSTOMER, purchases)


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("staff", f"staff@{DEMO_EMAIL_DOMAIN}", "Sam Staff", Role.STAFF),
    _customer("alice", "Alice Archer", DemoPurchase("backpack", 4500, 0)),
    _customer("bob", "Bob Baker", DemoPurchase("water_bottle", 2500, 30)),
    _customer("carol", "Carol Chen", DemoPurchase("headphones", 8000, 31)),
    _customer("dave", "Dave Diaz", DemoPurchase("mouse", 3000, -2)),
    _customer("erin", "Erin Evans", DemoPurchase("monitor", 12900, 5)),
    _customer(
        "frank",
        "Frank Foster",
        DemoPurchase("desk_lamp", 6000, 3),
        DemoPurchase("canvas", 6000, 3),
    ),
    _customer(
        "grace",
        "Grace Green",
        DemoPurchase("backpack", 4500, 10),
        DemoPurchase("mouse", 3000, 45),
    ),
    _customer("heidi", "Heidi Hall"),
)


def build_demo_repository(today: date) -> InMemoryRepository:
    """The same demo data in memory, with dates resolved against ``today``."""
    profiles = [
        Profile(id=demo_uuid("user", u.key), display_name=u.display_name, role=u.role)
        for u in DEMO_USERS
    ]
    purchases = [
        Purchase(
            id=demo_uuid("purchase", u.key, str(i)),
            customer_id=demo_uuid("user", u.key),
            item_name=p.item_name,
            price_cents=p.price_cents,
            purchased_on=today - timedelta(days=p.days_ago),
        )
        for u in DEMO_USERS
        for i, p in enumerate(u.purchases)
    ]
    return InMemoryRepository(profiles=profiles, purchases=purchases)
