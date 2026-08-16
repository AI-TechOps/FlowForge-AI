"""Tenant-scoped row access (D7, D18 decision 7).

Every load of a tenant-owned row goes through here. The rule it enforces is
one line — the row must belong to the acting organization, and a row that does
not is *absent*, never forbidden — but the reason it exists as a helper is
subtler.

`session.get(Model, id)` followed by `if row.org_id != org_id` is correct only
for the row you remembered to check. Phase 4's adversarial pass found the gap:
`GET /api/approvals/{id}` scoped the approval, then followed `approval.run_id`
and `run.ticket_id` by primary key with no predicate at all. The foreign key
covers `run_id`, not `(org_id, run_id)`, so one inconsistent relationship —
from a worker bug, a migration, a botched repair — turned into a cross-tenant
disclosure of another organization's run, evidence, and ticket.

Scoping the *entry point* is not enough. Every hop has to be scoped, including
the ones that look like they cannot cross a boundary because a foreign key
"already guarantees" it. It does not; it guarantees referential integrity, not
tenancy.

`scripts/check_tenant_scoping.py` fails the build on a direct `session.get` of
a tenant model outside this module, so the next hop cannot quietly skip it.
"""

import uuid
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import TenantBase

ModelT = TypeVar("ModelT", bound=TenantBase)


async def get_scoped(
    session: AsyncSession,
    model: type[ModelT],
    row_id: uuid.UUID | None,
    org_id: uuid.UUID,
) -> ModelT | None:
    """Load one row of `model` by id, or None if it is not this org's.

    `None` for a foreign row rather than an exception: callers turn it into a
    404, and the tenant boundary must never distinguish "does not exist" from
    "exists and is someone else's" (D7).
    """
    if row_id is None:
        return None
    row = await session.get(model, row_id)
    if row is None or row.org_id != org_id:
        return None
    return row
