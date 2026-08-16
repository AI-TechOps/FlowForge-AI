"""Fail the build on an unscoped load of a tenant-owned row (D18 decision 7).

Spec 05 §3 asks for a single query-scoping utility plus an automated check
against direct unscoped tenant queries. `app/tenancy.get_scoped` is the
utility; this is the check, and it exists because the review convention on its
own already failed twice — Codex found a run-scoped call recorder leaking
across tenants in Phase 3, and an approval card following `run_id` into another
organization in Phase 4.

What it flags: any `.get(<TenantModel>, ...)` under `app/`, outside the helper
itself. That is the shape that reads as safe — the id came from a scoped row,
so surely it belongs to us — and is not.

Workers were originally excluded on the grounds that they re-check the org from
the job payload. They do, for the row the payload names; they did not for the
rows that row points at. An org-A run naming an org-B ticket had that ticket
moved from `new` to `actioned` by finalization, and the exclusion is exactly
why the first version of this check did not see it.

What it deliberately does not flag: `select(...)` statements. Those carry
explicit `.where(Model.org_id == ...)` predicates that this would have to
understand to judge, and a checker that guesses would either be noisy enough to
be disabled or lax enough to be pointless. Workers are excluded for the same
reason: they receive `org_id` in the job payload and re-check it against the
row they loaded, which is the same guarantee reached a different way.

An AST walk rather than a regex: a comment or a string mentioning session.get
is not a defect, and a checker that cries wolf gets switched off.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "backend" / "app"
MODELS_ROOT = APP_ROOT / "models"
# The helper itself is the one place allowed to load a tenant row by id.
EXEMPT = {APP_ROOT / "tenancy.py"}


def tenant_models() -> set[str]:
    """Class names that inherit TenantBase, read from the model modules."""
    names: set[str] = set()
    for path in MODELS_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "TenantBase"
                for base in node.bases
            ):
                names.add(node.name)
    return names


def violations(models: set[str]) -> list[str]:
    found: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path in EXEMPT:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not (isinstance(function, ast.Attribute) and function.attr == "get"):
                continue
            # Any receiver: `session.get`, `self.session.get`,
            # `context.session.get`. Keying on the name `session` missed the
            # adapter's `self.session.get`, and a checker that only catches the
            # spelling you thought of is not a control.
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id in models:
                found.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    f".get({first.id}, ...) is unscoped; "
                    f"use app.tenancy.get_scoped(session, {first.id}, id, org_id)"
                )
    return found


def main() -> int:
    models = tenant_models()
    if not models:
        print("tenant scoping check: found no TenantBase models — is the layout right?")
        return 1

    found = violations(models)
    if found:
        print("tenant scoping check FAILED:")
        for line in found:
            print(f"  {line}")
        return 1

    print(
        f"tenant scoping check passed; {len(models)} tenant models, "
        "no unscoped loads anywhere under app/"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
