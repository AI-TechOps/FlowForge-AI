from __future__ import annotations

import ast
import re
from pathlib import Path

REQUIRED_PATHS = (
    ".env.example",
    "backend/Dockerfile",
    "backend/alembic.ini",
    "backend/app/config.py",
    "backend/app/db.py",
    "backend/app/llm/provider.py",
    "backend/app/main.py",
    "backend/app/models",
    "backend/pyproject.toml",
    "frontend/Dockerfile",
    "frontend/package.json",
    "frontend/src/App.tsx",
    "frontend/src/main.tsx",
    "infra/docker-compose.yml",
    "infra/init-db.sql",
    "scripts/seed.py",
)

REQUIRED_ENVIRONMENT_KEYS = {
    "APP_ENV",
    "DATABASE_URL",
    "EMBEDDING_MODEL",
    "LLM_PROVIDER",
    "OLLAMA_BASE_URL",
    "OPENAI_API_KEY",
    "REDIS_URL",
}

PROVIDER_IMPORT_ROOTS = {
    "langchain_ollama",
    "langchain_openai",
    "ollama",
    "openai",
}


def _contains_color_family(source: str, family: str) -> bool:
    if family in source:
        return True
    for match in re.finditer(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})\b", source):
        digits = match.group()[1:]
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        red = int(digits[0:2], 16)
        green = int(digits[2:4], 16)
        blue = int(digits[4:6], 16)
        if family == "green" and green > red * 1.2 and green > blue * 1.2:
            return True
        if family == "red" and red > green * 1.2 and red > blue * 1.2:
            return True
    for match in re.finditer(r"hsla?\(\s*([0-9.]+)", source):
        hue = float(match.group(1)) % 360
        if family == "green" and 75 <= hue <= 165:
            return True
        if family == "red" and (hue <= 25 or hue >= 335):
            return True
    return False


def _dotenv_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    assignment = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = assignment.match(line.strip())
        if match:
            keys.add(match.group(1))
    return keys


def _provider_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", maxsplit=1)[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])
    return imported_roots & PROVIDER_IMPORT_ROOTS


def test_phase0_repository_skeleton_exists(repository_root: Path) -> None:
    missing = [
        relative
        for relative in REQUIRED_PATHS
        if not (repository_root / relative).exists()
    ]
    assert not missing, f"Phase 0 repository skeleton is missing: {missing}"


def test_env_example_documents_the_complete_phase0_contract(
    repository_root: Path,
) -> None:
    env_path = repository_root / ".env.example"
    assert env_path.is_file(), ".env.example is required"
    missing = REQUIRED_ENVIRONMENT_KEYS - _dotenv_keys(env_path)
    assert not missing, f".env.example does not document: {sorted(missing)}"


def test_provider_sdks_are_confined_to_the_factory(repository_root: Path) -> None:
    app_dir = repository_root / "backend" / "app"
    factory = app_dir / "llm" / "provider.py"
    assert factory.is_file(), "Phase 0 requires backend/app/llm/provider.py"

    violations: dict[str, list[str]] = {}
    for path in sorted(app_dir.rglob("*.py")):
        provider_imports = _provider_imports(path)
        if provider_imports and path != factory:
            violations[str(path.relative_to(repository_root))] = sorted(
                provider_imports
            )
    assert not violations, (
        f"provider SDK imports outside the provider factory: {violations}"
    )


def test_readme_documents_phase0_operator_workflows(repository_root: Path) -> None:
    readme_path = repository_root / "README.md"
    assert readme_path.is_file(), "README.md is required"
    readme = readme_path.read_text(encoding="utf-8").lower()

    assert "docker compose" in readme, "README must explain how to run the stack"
    assert "seed" in readme, "README must explain how to seed the demo tenant"
    assert "llm_provider" in readme, "README must explain how to switch LLM providers"


def test_frontend_calls_health_api_and_defines_green_and_red_states(
    repository_root: Path,
) -> None:
    app_path = repository_root / "frontend" / "src" / "App.tsx"
    assert app_path.is_file(), "frontend/src/App.tsx is required"
    app_source = app_path.read_text(encoding="utf-8").lower()
    all_frontend_source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted((repository_root / "frontend" / "src").rglob("*"))
        if path.suffix in {".css", ".ts", ".tsx"}
    )
    assert "/api/health" in app_source, "frontend must call the backend health endpoint"
    assert _contains_color_family(all_frontend_source, "green"), (
        "frontend must define a green healthy state"
    )
    assert _contains_color_family(all_frontend_source, "red"), (
        "frontend must define a red unhealthy state"
    )
