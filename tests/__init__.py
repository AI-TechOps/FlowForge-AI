"""Test suites, packaged deliberately.

Each phase directory has its own `conftest.py`, and several share test-module
basenames. Without `__init__.py` files pytest imports all of them under bare
top-level names (`conftest`, `test_tenant_isolation_gate`), so whichever loads
first wins and the rest resolve against the wrong module — `pytest tests/phase1
tests/phase2` used to fail collection for exactly that reason.

Packaging makes the module names fully qualified, so the suites are importable
in any combination. Shared helpers are imported relatively (`from .conftest
import ...`) to keep that guarantee.
"""
