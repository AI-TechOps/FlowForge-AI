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
    """Use the Phase 4-specific URL when set, otherwise CI's shared URL."""
    value = os.environ.get("PHASE4_DATABASE_URL", os.environ.get("DATABASE_URL"))
    if not value:
        pytest.skip("PHASE4_DATABASE_URL or DATABASE_URL is required")
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
