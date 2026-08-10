"""Agent package.

Importing this package populates the tool registry with BOTH read and write
tools. Registration used to depend on some caller happening to import
`write_tools` first, which meant `get_tool("assign_ticket")` raised
`unknown tool` in any process that had not — a failure mode that would have
surfaced as a broken approval resume rather than an import error.
"""

from app.agents import write_tools as _write_tools  # noqa: F401  (registers write tools)
