"""Shared live-stack fixtures for adversarial probes."""

import os

import pytest

from tests.phase2.conftest import (
    corpus_org_id,
    corpus_ready,
    empty_org_id,
    ingested_phase2_corpus,
    isolation_org_ids,
    phase2_client,
    phase2_organization_ids,
    repository_root,
)
from tests.phase3.conftest import (
    approver_user_ids,
    mock_adapter_control,
    phase3_client,
    phase3_database_url,
    phase3_evidence_ready,
    phase3_org_id,
    phase3_principals,
)
from tests.phase4.conftest import phase4_client, phase4_principals


@pytest.fixture(scope="session")
def phase4_database_url() -> str:
    """The database backing the live stack.

    Deliberately no fallback to DATABASE_URL. In the fast `test` job that
    variable points at the *migration scratch* database — a database another
    gate deliberately cycles down to base and back — and the two probes here
    that need only a database, not the API, would happily run against it:
    before the migration gate has built the schema, or after it has torn it
    down. That produced failures that had nothing to do with the product.

    Requiring the explicit variable means these skip in the fast job, which is
    correct — they are live-stack probes — and the integration job sets it.
    """
    value = os.environ.get("PHASE4_DATABASE_URL")
    if not value:
        pytest.skip("PHASE4_DATABASE_URL is required for the live Phase 4 probes")
    return value


__all__ = [
    "approver_user_ids",
    "corpus_org_id",
    "corpus_ready",
    "empty_org_id",
    "ingested_phase2_corpus",
    "isolation_org_ids",
    "mock_adapter_control",
    "phase2_client",
    "phase2_organization_ids",
    "phase3_client",
    "phase3_database_url",
    "phase3_evidence_ready",
    "phase3_org_id",
    "phase3_principals",
    "phase4_client",
    "phase4_database_url",
    "phase4_principals",
    "repository_root",
]
