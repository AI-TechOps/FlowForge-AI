"""Seed the demo org and its users (Phase 0, extended in Phase 4).

Run from the repo root with the backend deps installed:
    python scripts/seed.py

Idempotent: re-running finds the existing rows and makes no duplicates.

The three personas are seeded as *distinct people* on purpose. CLAUDE.md
requires at least one Operator and one Approver who are not the same user, so
the hand-off in the MVP journey — one person triages, a different person
authorises the write — is demonstrable rather than asserted. `demo@demo` holds
all three roles for convenience when recording the demo; it is a shortcut for
one narrator, not the shape the system assumes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import async_session_factory, engine
from app.models import Organization, Role, User, UserRole
from sqlalchemy import select
from sqlalchemy.orm import selectinload

DEMO_ORG = "Meridian Dynamics"

# email -> roles. Segregation of duties (D4) is why operator and approver are
# separate rows: the agent proposes, and a human who is not the proposer
# authorises.
SEED_USERS: dict[str, tuple[Role, ...]] = {
    "admin@demo": (Role.administrator,),
    "operator@demo": (Role.operator,),
    "approver@demo": (Role.approver,),
    "demo@demo": (Role.administrator, Role.operator, Role.approver),
}


async def seed() -> None:
    async with async_session_factory() as session:
        org = (
            await session.execute(
                select(Organization).where(Organization.name == DEMO_ORG)
            )
        ).scalar_one_or_none()
        if org is None:
            org = Organization(name=DEMO_ORG)
            session.add(org)
            await session.flush()
            print(f"Created organization {org.name} ({org.id})")
        else:
            print(f"Organization {org.name} already exists ({org.id})")

        for email, roles in SEED_USERS.items():
            user = (
                await session.execute(
                    select(User)
                    .where(User.org_id == org.id, User.email == email)
                    .options(selectinload(User.roles))
                )
            ).scalar_one_or_none()
            if user is None:
                user = User(org_id=org.id, email=email)
                session.add(user)
                await session.flush()
                print(f"Created user {user.email} ({user.id})")
                # A user built in this session has no loaded `roles` collection,
                # and touching it would lazy-load under async — which raises
                # MissingGreenlet rather than emitting a query. It is new, so
                # it holds nothing.
                held: set[Role] = set()
            else:
                print(f"User {user.email} already exists ({user.id})")
                held = {grant.role for grant in user.roles}

            for role in roles:
                if role in held:
                    print(f"  {email} already has the {role.value} role")
                    continue
                session.add(UserRole(user_id=user.id, role=role))
                print(f"  Granted {role.value} to {email}")

        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
