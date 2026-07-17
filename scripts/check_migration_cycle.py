#!/usr/bin/env python3
"""Run Alembic upgrade, downgrade, and upgrade against a scratch database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence
from urllib.parse import unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKEND_DIR = PROJECT_ROOT / "backend"
SAFE_DATABASE_MARKERS = ("ci", "scratch", "test")
SYSTEM_DATABASE_NAMES = frozenset({"postgres", "template0", "template1"})


def database_name(database_url: str) -> str:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {
        "postgres",
        "postgresql",
        "postgresql+asyncpg",
        "postgresql+psycopg",
    }:
        raise ValueError("database URL must use a PostgreSQL scheme")
    name = unquote(parsed.path.lstrip("/")).strip()
    if not name:
        raise ValueError("database URL must name a database")
    return name


def require_scratch_database(database_url: str) -> str:
    name = database_name(database_url)
    lowered = name.lower()
    if lowered in SYSTEM_DATABASE_NAMES or not any(
        marker in lowered for marker in SAFE_DATABASE_MARKERS
    ):
        markers = ", ".join(SAFE_DATABASE_MARKERS)
        raise ValueError(
            f"refusing migration cycle for database {name!r}; a dedicated scratch "
            f"database name must contain one of: {markers}"
        )
    return name


def run_cycle(
    *,
    database_url: str,
    backend_dir: Path,
    alembic_config: Path,
    python_executable: str,
    environment: Mapping[str, str] | None = None,
) -> None:
    require_scratch_database(database_url)
    if not backend_dir.is_dir():
        raise ValueError(f"backend directory does not exist: {backend_dir}")
    if not alembic_config.is_file():
        raise ValueError(f"Alembic config does not exist: {alembic_config}")

    command_prefix = [
        python_executable,
        "-m",
        "alembic",
        "-c",
        str(alembic_config),
    ]
    cycle = (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head"))
    child_environment = dict(os.environ if environment is None else environment)
    child_environment["DATABASE_URL"] = database_url

    for operation in cycle:
        command = [*command_prefix, *operation]
        print(f"running: {' '.join(command)}")
        subprocess.run(
            command,
            cwd=backend_dir,
            env=child_environment,
            check=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("MIGRATION_TEST_DATABASE_URL"),
        help=(
            "dedicated scratch PostgreSQL URL; defaults to "
            "MIGRATION_TEST_DATABASE_URL"
        ),
    )
    parser.add_argument(
        "--backend-dir",
        type=Path,
        default=DEFAULT_BACKEND_DIR,
    )
    parser.add_argument(
        "--alembic-config",
        type=Path,
        default=DEFAULT_BACKEND_DIR / "alembic.ini",
    )
    parser.add_argument("--python", default=sys.executable, dest="python_executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        print(
            "missing scratch database URL; set MIGRATION_TEST_DATABASE_URL or "
            "pass --database-url",
            file=sys.stderr,
        )
        return 2

    try:
        scratch_name = require_scratch_database(args.database_url)
        print(f"validated scratch database: {scratch_name}")
        run_cycle(
            database_url=args.database_url,
            backend_dir=args.backend_dir.resolve(),
            alembic_config=args.alembic_config.resolve(),
            python_executable=args.python_executable,
        )
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"migration cycle failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
