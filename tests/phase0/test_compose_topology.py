from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# Phase 1 (spec 02, task 4) adds the arq `worker` as its own compose service on
# the backend image; the Phase 0 topology of four services is now five.
EXPECTED_SERVICES = {"backend", "db", "frontend", "redis", "worker"}


def _compose_config(compose_path: Path) -> dict[str, object]:
    if shutil.which("docker") is None:
        pytest.skip(
            "Docker CLI is unavailable; compose contract requires Docker Compose"
        )
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "config", "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"docker compose config failed:\n{result.stderr}"
    return json.loads(result.stdout)


def _published_targets(service: dict[str, object]) -> set[int]:
    targets: set[int] = set()
    for port in service.get("ports", []):
        if isinstance(port, dict) and "target" in port:
            targets.add(int(port["target"]))
        elif isinstance(port, str):
            targets.add(int(port.rsplit(":", maxsplit=1)[-1].split("/", maxsplit=1)[0]))
    return targets


def test_compose_defines_the_locked_service_topology(
    repository_root: Path,
) -> None:
    compose_path = repository_root / "infra" / "docker-compose.yml"
    assert compose_path.is_file(), "infra/docker-compose.yml is required"
    config = _compose_config(compose_path)
    services = config.get("services")
    assert isinstance(services, dict)
    assert set(services) == EXPECTED_SERVICES

    db = services["db"]
    redis = services["redis"]
    backend = services["backend"]
    frontend = services["frontend"]
    worker = services["worker"]
    assert isinstance(db, dict)
    assert isinstance(redis, dict)
    assert isinstance(backend, dict)
    assert isinstance(frontend, dict)
    assert isinstance(worker, dict)

    # The worker reuses the backend image with the arq command and waits on the
    # same healthy dependencies (spec 02, task 4).
    assert worker.get("build"), "worker service must build backend/Dockerfile"
    worker_command = worker.get("command")
    rendered_command = (
        worker_command
        if isinstance(worker_command, str)
        else " ".join(worker_command or [])
    )
    assert "arq" in rendered_command, "worker service must run the arq worker"
    worker_dependencies = worker.get("depends_on")
    assert isinstance(worker_dependencies, dict)
    for service_name in ("db", "redis"):
        dependency = worker_dependencies.get(service_name)
        assert isinstance(dependency, dict)
        assert dependency.get("condition") == "service_healthy"

    assert db.get("image") == "pgvector/pgvector:pg16"
    assert str(redis.get("image", "")).startswith("redis:7")
    assert db.get("healthcheck"), "db service must define a healthcheck"
    assert redis.get("healthcheck"), "redis service must define a healthcheck"
    assert backend.get("build"), "backend service must build backend/Dockerfile"
    assert frontend.get("build"), "frontend service must build frontend/Dockerfile"
    assert 8000 in _published_targets(backend)
    assert 5173 in _published_targets(frontend)

    dependencies = backend.get("depends_on")
    assert isinstance(dependencies, dict)
    for service_name in ("db", "redis"):
        dependency = dependencies.get(service_name)
        assert isinstance(dependency, dict)
        assert dependency.get("condition") == "service_healthy"


def test_database_initialization_enables_pgvector(repository_root: Path) -> None:
    init_path = repository_root / "infra" / "init-db.sql"
    assert init_path.is_file(), "infra/init-db.sql is required"
    normalized_sql = re.sub(r"\s+", " ", init_path.read_text(encoding="utf-8")).lower()
    assert re.search(r"create extension if not exists (?:\"?vector\"?)", normalized_sql)
