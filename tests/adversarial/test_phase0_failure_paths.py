from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run_python(
    source: str, *, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _backend_environment(**overrides: str) -> dict[str, str]:
    environment = dict(os.environ)
    python_path = str(REPOSITORY_ROOT / "backend")
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{python_path}{os.pathsep}{existing_python_path}"
        if existing_python_path
        else python_path
    )
    environment.update(
        {
            "DATABASE_URL": "postgresql+asyncpg://flowforge:flowforge@127.0.0.1:1/flowforge_test",
            "REDIS_URL": "redis://127.0.0.1:1/0",
            **overrides,
        }
    )
    return environment


def test_health_check_degrades_instead_of_crashing_for_malformed_redis_url() -> None:
    pytest.importorskip("redis")
    pytest.importorskip("sqlalchemy")
    result = _run_python(
        """
import asyncio
from app.api.health import _check_redis

status = asyncio.run(_check_redis())
assert status == "error", status
""",
        environment=_backend_environment(REDIS_URL="not-a-redis-url"),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_openai_provider_rejects_a_whitespace_only_api_key() -> None:
    pytest.importorskip("pydantic_settings")
    result = _run_python(
        """
from app.config import Settings
from app.llm.provider import get_provider

settings = Settings(
    database_url="postgresql+asyncpg://flowforge:flowforge@127.0.0.1:1/flowforge_test",
    redis_url="redis://127.0.0.1:1/0",
    llm_provider="openai",
    openai_api_key="   ",
)
try:
    get_provider(settings)
except ValueError:
    pass
else:
    raise AssertionError("whitespace-only OPENAI_API_KEY was accepted")
""",
        environment=_backend_environment(),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("database_name", ["contest", "social"])
def test_migration_runner_rejects_incidental_scratch_marker_substrings(
    database_name: str,
    tmp_path: Path,
) -> None:
    runner = REPOSITORY_ROOT / "scripts" / "check_migration_cycle.py"
    result = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--database-url",
            f"postgresql+asyncpg://localhost/{database_name}",
            "--backend-dir",
            str(tmp_path / "missing-backend"),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "refusing migration cycle" in result.stderr


@pytest.mark.parametrize(
    "planted_import, expected_name",
    [
        (
            'import importlib as loader\nloader.import_module("tests.helpers")',
            "tests.helpers",
        ),
        (
            'from importlib import import_module\nimport_module("scripts.seed")',
            "scripts.seed",
        ),
        ('import builtins\nbuiltins.__import__("fixtures")', "fixtures"),
    ],
)
def test_isolation_guard_rejects_aliased_dynamic_imports(
    planted_import: str,
    expected_name: str,
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "backend" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "planted.py").write_text(f"{planted_import}\n", encoding="utf-8")

    guard = REPOSITORY_ROOT / "scripts" / "check_runtime_isolation.py"
    result = subprocess.run(
        [sys.executable, str(guard), "--app-dir", str(app_dir)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert expected_name in result.stdout
