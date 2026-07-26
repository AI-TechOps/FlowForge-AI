from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def guard_script(repository_root: Path) -> Path:
    path = repository_root / "scripts" / "check_runtime_isolation.py"
    assert path.is_file(), "the Phase 0 runtime isolation guard is required"
    return path


def _run_guard(script: Path, app_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--app-dir", str(app_dir)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_isolation_guard_accepts_runtime_only_imports(
    guard_script: Path, tmp_path: Path
) -> None:
    app_dir = tmp_path / "backend" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "main.py").write_text(
        "import os\nfrom pathlib import Path\n", encoding="utf-8"
    )

    result = _run_guard(guard_script, app_dir)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "planted_import, expected_root",
    [
        ("import tests.phase0", "tests.phase0"),
        ("from scripts import seed", "scripts"),
        ("import fixtures as demo_data", "fixtures"),
        ('__import__("tests.helpers")', "tests.helpers"),
        ('import importlib\nimportlib.import_module("scripts.seed")', "scripts.seed"),
    ],
)
def test_isolation_guard_fails_for_a_planted_development_import(
    guard_script: Path,
    tmp_path: Path,
    planted_import: str,
    expected_root: str,
) -> None:
    app_dir = tmp_path / "backend" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "planted.py").write_text(f"{planted_import}\n", encoding="utf-8")

    result = _run_guard(guard_script, app_dir)
    assert result.returncode == 1
    assert "forbidden runtime import" in result.stdout
    assert expected_root in result.stdout


def test_repository_runtime_passes_the_isolation_guard(
    guard_script: Path, repository_root: Path
) -> None:
    result = _run_guard(guard_script, repository_root / "backend" / "app")
    assert result.returncode == 0, result.stdout + result.stderr
