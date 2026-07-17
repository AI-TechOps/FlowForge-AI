"""Seed the demo org and admin user (Phase 0).

Run from the repo root with the backend deps installed:
    python scripts/seed.py

Idempotent: re-running finds the existing rows and makes no duplicates.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import async_session_factory, engine  # noqa: E402
from app.models import Organization, Role, User, UserRole  # noqa: E402

DEMO_ORG = "Meridian Dynamics"
ADMIN_EMAIL = "admin@demo"


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

        user = (
            await session.execute(
                select(User).where(User.org_id == org.id, User.email == ADMIN_EMAIL)
            )
        ).scalar_one_or_none()
        if user is None:
            user = User(org_id=org.id, email=ADMIN_EMAIL)
            session.add(user)
            await session.flush()
            print(f"Created user {user.email} ({user.id})")
        else:
            print(f"User {user.email} already exists ({user.id})")

        role = (
            await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id, UserRole.role == Role.administrator
                )
            )
        ).scalar_one_or_none()
        if role is None:
            session.add(UserRole(user_id=user.id, role=Role.administrator))
            print(f"Granted administrator role to {user.email}")
        else:
            print(f"{user.email} already has the administrator role")

        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
