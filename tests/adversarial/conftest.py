"""Shared live-stack fixtures for Phase 2 adversarial probes."""

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
    "repository_root",
]
