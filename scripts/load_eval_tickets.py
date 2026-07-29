"""Load the labeled eval ticket seed set into the tickets table.

The fixtures were committed in Phase 1; the loader lands now because `tickets`
is a Phase 2 table (spec 02 §5). Idempotent: tickets are matched by their
fixture id carried in external_ref, so re-running updates instead of
duplicating.

    python scripts/load_eval_tickets.py [--org-id UUID] [--include-demo]

Labels (`labels`, `grounding_references`) are deliberately NOT loaded into the
tickets table — they are the answer key, and the agent must never see them.
Phase 5's eval harness reads them straight from the fixture.
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db import async_session_factory, engine  # noqa: E402
from app.models import Organization, Ticket, TicketStatus  # noqa: E402
from sqlalchemy import select  # noqa: E402

FIXTURE = REPO_ROOT / "fixtures" / "eval_tickets.json"


async def load(org_id: uuid.UUID | None, include_demo: bool) -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    records = list(data["eval_tickets"])
    if include_demo:
        records += list(data.get("demo_tickets", []))

    async with async_session_factory() as session:
        if org_id is None:
            org_id = (
                await session.execute(
                    select(Organization.id).order_by(Organization.created_at).limit(1)
                )
            ).scalar_one_or_none()
            if org_id is None:
                raise SystemExit("no organization found; run scripts/seed.py first")

        created = updated = 0
        for record in records:
            fixture_id = record["id"]
            is_eval = fixture_id.startswith("EVAL-")
            existing = (
                await session.execute(
                    select(Ticket).where(
                        Ticket.org_id == org_id, Ticket.external_ref == fixture_id
                    )
                )
            ).scalar_one_or_none()

            target = existing or Ticket(
                org_id=org_id, external_ref=fixture_id, status=TicketStatus.new
            )
            target.title = record["title"]
            target.description = record["description"]
            target.department = record.get("requester_department")
            target.service = record.get("affected_service")
            target.priority = record.get("existing_priority")
            target.is_eval_seed = is_eval
            target.created_by = "eval-seed"

            if existing is None:
                session.add(target)
                created += 1
            else:
                updated += 1

        await session.commit()
    await engine.dispose()
    print(f"org {org_id}: {created} created, {updated} updated ({len(records)} in fixture)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", type=uuid.UUID, default=None)
    parser.add_argument("--include-demo", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(load(arguments.org_id, arguments.include_demo))
