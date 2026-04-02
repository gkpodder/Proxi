"""Factory and registration helpers for coding tools."""

from pathlib import Path

from proxi.tools.base import BaseTool
from proxi.tools.diff import ApplyPatchTool
from proxi.tools.filesystem import EditFileTool
from proxi.tools.glob_tool import GlobTool
from proxi.tools.grep import GrepTool
from proxi.tools.path_guard import PathGuard
from proxi.tools.shell import ExecuteCodeTool

# Canonical names for all coding tools — used to unregister them on working-dir change.
CODING_TOOL_NAMES: tuple[str, ...] = (
    "grep",
    "glob",
    "edit_file",
    "apply_patch",
    "execute_code",
)

# Filesystem tools registered by setup_tools() that also need to be re-rooted
# when the working directory changes.
FILESYSTEM_TOOL_NAMES: tuple[str, ...] = (
    "read_file",
    "write_file",
)


def unregister_coding_tools(registry: "ToolRegistry") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Remove all coding tools from a registry (live + deferred tiers)."""
    for name in CODING_TOOL_NAMES:
        registry._tools.pop(name, None)
        if name in registry._deferred_tools:
            registry._deferred_tools.pop(name)
            registry._rebuild_deferred_index()
    registry._schema_injected -= set(CODING_TOOL_NAMES)


def build_coding_tools(working_dir: Path | None = None) -> list[BaseTool]:
    """Return all coding tools initialized with the given working directory.

    Tools that operate on file paths use PathGuard to restrict access to
    working_dir.  Shell execution is also rooted there.
    """
    guard = PathGuard(working_dir)
    cwd = working_dir or Path.cwd()
    return [
        GrepTool(guard),
        GlobTool(guard),
        EditFileTool(guard),
        ApplyPatchTool(cwd),
        ExecuteCodeTool(working_directory=cwd, guard=guard),
    ]


def register_coding_tools(
    registry: "ToolRegistry",  # type: ignore[name-defined]  # noqa: F821
    working_dir: Path | None = None,
    tier: str = "live",
) -> None:
    """Register coding tools into a ToolRegistry at the specified tier.

    Args:
        registry: The ToolRegistry to register tools into.
        working_dir: Root directory for path-guarded operations.
        tier: 'live' (always in context), 'deferred' (discovered via search_tools),
              or 'disabled' (skip registration entirely).
    """
    if tier == "disabled":
        return

    tools = build_coding_tools(working_dir)
    for tool in tools:
        if tier == "deferred":
            registry.register_deferred(tool)
        else:
            registry.register(tool)
