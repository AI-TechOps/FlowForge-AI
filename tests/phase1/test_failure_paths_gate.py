from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

import pytest

from conftest import (
    Phase1Client,
    document_id_from,
    response_detail,
    wait_for_document_status,
)


MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def test_g1_4_upload_rejects_unsupported_file_type(
    phase1_client: Phase1Client,
    org_a_id: str,
) -> None:
    response = phase1_client.upload_bytes(
        org_id=org_a_id,
        filename="unsupported.csv",
        title="Unsupported file gate",
        content=b"not,an,accepted,format\n",
    )
    assert response.status == 415, response_detail(response)


def test_g1_4_upload_rejects_file_larger_than_twenty_megabytes(
    phase1_client: Phase1Client,
    org_a_id: str,
) -> None:
    response = phase1_client.upload_bytes(
        org_id=org_a_id,
        filename="oversized.txt",
        title="Oversized file gate",
        content=b"x" * (MAX_UPLOAD_BYTES + 1),
    )
    assert response.status == 413, response_detail(response)


def test_g1_4_corrupt_accepted_file_fails_with_human_readable_error_within_60s(
    phase1_client: Phase1Client,
    org_a_id: str,
) -> None:
    started = time.monotonic()
    response = phase1_client.upload_bytes(
        org_id=org_a_id,
        filename="corrupt-but-accepted.pdf",
        title="Corrupt PDF gate",
        content=b"%PDF-1.7\nthis is not a valid PDF structure\n%%EOF",
    )
    assert response.status == 202, response_detail(response)
    document_id = document_id_from(response)

    status, _ = wait_for_document_status(
        phase1_client,
        org_id=org_a_id,
        document_id=document_id,
        terminal_statuses={"ready", "failed"},
        timeout=60,
    )
    elapsed = time.monotonic() - started
    assert status["status"] == "failed", status
    assert elapsed <= 60, f"corrupt ingestion took {elapsed:.2f}s to fail"
    error_message = status.get("error_message")
    assert isinstance(error_message, str) and len(error_message.strip()) >= 8
    assert any(
        character.isalpha() for character in error_message
    ), f"error_message is not human-readable: {error_message!r}"


def _run_compose(
    repository_root: Path,
    compose_file: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", compose_file, *arguments],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )


def test_g1_4_killed_worker_document_is_recoverable_via_reingest(
    repository_root: Path,
    phase1_client: Phase1Client,
    org_a_id: str,
    ensure_worker_running: None,
) -> None:
    del ensure_worker_running
    if os.environ.get("PHASE1_MANAGE_WORKER", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        pytest.skip(
            "set PHASE1_MANAGE_WORKER=1 on an isolated gate stack to run the "
            "destructive worker kill-and-recovery check"
        )
    if shutil.which("docker") is None:
        pytest.fail("Docker CLI is required when PHASE1_MANAGE_WORKER=1")

    compose_file = os.environ.get(
        "PHASE1_COMPOSE_FILE",
        str(repository_root / "infra" / "docker-compose.yml"),
    )
    stopped = _run_compose(repository_root, compose_file, "stop", "worker")
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr

    marker = uuid4().hex
    slow_content = (
        f"Worker crash recovery probe {marker}. "
        "This repeated content creates enough chunks to observe processing.\n" * 50_000
    ).encode()
    response = phase1_client.upload_bytes(
        org_id=org_a_id,
        filename=f"worker-recovery-{marker}.txt",
        title=f"Worker Recovery Probe {marker}",
        content=slow_content,
    )
    assert response.status == 202, response_detail(response)
    document_id = document_id_from(response)

    started = _run_compose(repository_root, compose_file, "up", "-d", "worker")
    assert started.returncode == 0, started.stdout + started.stderr
    processing, _ = wait_for_document_status(
        phase1_client,
        org_id=org_a_id,
        document_id=document_id,
        terminal_statuses={"processing", "ready", "failed"},
        timeout=30,
        interval=0.02,
    )
    assert processing["status"] == "processing", (
        "the worker completed before the gate could kill it mid-ingestion; "
        "the kill path was not exercised"
    )

    killed = _run_compose(repository_root, compose_file, "kill", "worker")
    assert killed.returncode == 0, killed.stdout + killed.stderr
    stranded = phase1_client.document_status(org_a_id, document_id)
    assert stranded.status == 200, response_detail(stranded)
    assert isinstance(stranded.body, dict)
    assert stranded.body.get("status") == "processing"

    restarted = _run_compose(repository_root, compose_file, "up", "-d", "worker")
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr
    reingest = phase1_client.reingest(org_a_id, document_id)
    assert reingest.status in {200, 202}, response_detail(reingest)
    recovered, _ = wait_for_document_status(
        phase1_client,
        org_id=org_a_id,
        document_id=document_id,
        terminal_statuses={"ready", "failed"},
        timeout=float(os.environ.get("PHASE1_INGEST_TIMEOUT_SECONDS", "120")),
    )
    assert recovered["status"] == "ready", recovered
