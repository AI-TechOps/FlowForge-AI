from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def migration_script(repository_root: Path) -> Path:
    path = repository_root / "scripts" / "check_migration_cycle.py"
    assert path.is_file(), "the Phase 0 migration cycle runner is required"
    return path


def test_migration_runner_refuses_a_non_scratch_database(
    migration_script: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(migration_script),
            "--database-url",
            "postgresql+asyncpg://localhost/flowforge",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "refusing migration cycle" in result.stderr


def test_initial_migration_survives_upgrade_downgrade_upgrade(
    migration_script: Path,
) -> None:
    database_url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is required for the destructive scratch-DB gate")

    result = subprocess.run(
        [sys.executable, str(migration_script), "--database-url", database_url],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
