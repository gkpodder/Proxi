"""Path guard utility for restricting file operations to a working directory."""

from pathlib import Path

from proxi.tools.base import ToolResult


class PathGuardError(ValueError):
    """Raised when a path violates the working directory constraint."""


class PathGuard:
    """Enforces that all file operations stay within a base directory.

    Resolves symlinks before comparison to prevent traversal attacks.
    When base_dir is None, all paths are permitted (no restriction).
    """

    def __init__(self, base_dir: Path | None) -> None:
        self._base: Path | None = base_dir.resolve() if base_dir is not None else None

    @property
    def base_dir(self) -> Path | None:
        return self._base

    def validate(self, path: str | Path) -> Path:
        """Resolve and validate that path is within base_dir.

        Returns the resolved absolute Path if valid.
        Raises PathGuardError if the path escapes the base directory.

        Relative paths are resolved relative to base_dir (not the process cwd)
        so that the agent can use bare filenames like "calculator.py" and have
        them land inside the working directory automatically.
        """
        p = Path(path).expanduser()
        if self._base is not None and not p.is_absolute():
            resolved = (self._base / p).resolve()
        else:
            resolved = p.resolve()
        if self._base is None:
            return resolved
        try:
            resolved.relative_to(self._base)
        except ValueError:
            raise PathGuardError(
                f"Path '{path}' is outside the working directory '{self._base}'"
            )
        return resolved

    def guard_result(self, path: str | Path) -> "tuple[Path | None, ToolResult | None]":
        """Validate path and return (resolved_path, None) on success,
        or (None, error_ToolResult) on violation.

        Convenience wrapper for tool execute() methods.
        """
        try:
            return self.validate(path), None
        except PathGuardError as e:
            return None, ToolResult(success=False, output="", error=str(e))
