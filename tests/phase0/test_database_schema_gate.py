from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest


def _psql_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(
        ("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


def _query(database_url: str, sql: str) -> list[str]:
    result = subprocess.run(
        [
            "psql",
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
            _psql_url(database_url),
            "--command",
            sql,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def migrated_scratch_database(repository_root: Path) -> str:
    database_url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "MIGRATION_TEST_DATABASE_URL is required for schema acceptance tests"
        )
    if shutil.which("psql") is None:
        pytest.skip("psql is required for schema acceptance tests")

    runner = repository_root / "scripts" / "check_migration_cycle.py"
    result = subprocess.run(
        [sys.executable, str(runner), "--database-url", database_url],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return database_url


def test_migrated_schema_contains_only_the_expected_domain_tables(
    migrated_scratch_database: str,
) -> None:
    tables = _query(
        migrated_scratch_database,
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
          AND table_name <> 'alembic_version'
        ORDER BY table_name;
        """,
    )
    # Head is 0002: Phase 1 (spec 02, task 1) adds documents + chunks alongside
    # the Phase 0 tenant tables. The gate still guards against stray tables.
    assert tables == ["chunks", "documents", "organizations", "user_roles", "users"]


def test_users_schema_has_tenant_link_and_never_stores_passwords(
    migrated_scratch_database: str,
) -> None:
    columns = set(
        _query(
            migrated_scratch_database,
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'users';
            """,
        )
    )
    assert {"id", "org_id", "email", "auth_subject", "created_at"} <= columns
    assert not {name for name in columns if "password" in name.lower()}


def test_user_roles_uses_the_locked_composite_primary_key(
    migrated_scratch_database: str,
) -> None:
    primary_key_columns = _query(
        migrated_scratch_database,
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.table_name = 'user_roles'
          AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position;
        """,
    )
    assert primary_key_columns == ["user_id", "role"]


def test_seed_script_creates_demo_org_admin_and_role(
    repository_root: Path,
    migrated_scratch_database: str,
) -> None:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = migrated_scratch_database
    result = subprocess.run(
        [sys.executable, str(repository_root / "scripts" / "seed.py")],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    seeded_rows = _query(
        migrated_scratch_database,
        """
        SELECT count(*)
        FROM organizations AS o
        JOIN users AS u ON u.org_id = o.id
        JOIN user_roles AS ur ON ur.user_id = u.id
        WHERE ur.role::text = 'administrator';
        """,
    )
    assert seeded_rows == ["1"]
