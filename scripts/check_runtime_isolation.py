#!/usr/bin/env python3
"""Fail when runtime code imports development-time Codex artifacts."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


FORBIDDEN_IMPORT_ROOTS = frozenset({"fixtures", "scripts", "tests"})
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, order=True)
class Violation:
    path: Path
    line: int
    column: int
    imported_name: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}:{self.column}: forbidden runtime import "
            f"{self.imported_name!r}"
        )


def _forbidden_root(imported_name: str) -> str | None:
    root = imported_name.lstrip(".").split(".", maxsplit=1)[0]
    return root if root in FORBIDDEN_IMPORT_ROOTS else None


def _literal_import_name(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first_argument = node.args[0]
    if not isinstance(first_argument, ast.Constant) or not isinstance(
        first_argument.value, str
    ):
        return None

    function = node.func
    if isinstance(function, ast.Name) and function.id == "__import__":
        return first_argument.value
    if (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "importlib"
        and function.attr == "import_module"
    ):
        return first_argument.value
    return None


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[Violation] = []

    def _record(self, node: ast.AST, imported_name: str) -> None:
        if _forbidden_root(imported_name) is None:
            return
        self.violations.append(
            Violation(
                path=self.path,
                line=getattr(node, "lineno", 1),
                column=getattr(node, "col_offset", 0) + 1,
                imported_name=imported_name,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._record(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module:
            self._record(node, node.module)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        imported_name = _literal_import_name(node)
        if imported_name is not None:
            self._record(node, imported_name)
        self.generic_visit(node)


def find_violations(app_dir: Path) -> tuple[list[Violation], list[str]]:
    violations: list[Violation] = []
    parse_errors: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append(f"{path}: cannot inspect Python source: {exc}")
            continue
        visitor = _ImportVisitor(path)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return sorted(violations), parse_errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-dir",
        type=Path,
        default=PROJECT_ROOT / "backend" / "app",
        help="runtime Python package to inspect (default: backend/app)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app_dir = args.app_dir.resolve()
    if not app_dir.is_dir():
        print(f"runtime application directory does not exist: {app_dir}")
        return 2

    violations, parse_errors = find_violations(app_dir)
    for message in parse_errors:
        print(message)
    for violation in violations:
        print(violation.render())

    if parse_errors or violations:
        return 1

    roots = ", ".join(sorted(FORBIDDEN_IMPORT_ROOTS))
    print(f"runtime isolation check passed; no imports from: {roots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
