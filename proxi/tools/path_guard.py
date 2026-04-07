"""Path guard utility for restricting file operations to a working directory."""

from pathlib import Path

from proxi.tools.base import ToolResult

DEFAULT_IGNORED_NAMES: frozenset[str] = frozenset({
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".git",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    "logs",
})


class PathGuardError(ValueError):
    """Raised when a path violates the working directory constraint."""


class PathGuard:
    """Enforces that all file operations stay within a base directory.

    Resolves symlinks before comparison to prevent traversal attacks.
    When base_dir is None, all paths are permitted (no restriction).
    """

    def __init__(self, base_dir: Path | None) -> None:
        self._base: Path | None = base_dir.resolve() if base_dir is not None else None
        self._ignored_names: frozenset[str] = DEFAULT_IGNORED_NAMES

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

    @property
    def ignored_names(self) -> frozenset[str]:
        return self._ignored_names

    def is_ignored(self, path: str | Path) -> bool:
        """Return True when path is under a default-ignored directory."""
        resolved = self.validate(path)
        parts = {part.lower() for part in resolved.parts}
        return any(name.lower() in parts for name in self._ignored_names)

    def guard_ignored_result(
        self,
        path: str | Path,
        *,
        include_ignored: bool = False,
    ) -> "tuple[Path | None, ToolResult | None]":
        """Validate path and enforce ignore policy unless explicitly overridden."""
        resolved, err = self.guard_result(path)
        if err is not None or resolved is None:
            return None, err
        if include_ignored:
            return resolved, None
        if self.is_ignored(resolved):
            return None, ToolResult(
                success=False,
                output="",
                error=(
                    f"Path '{path}' is in an ignored directory. "
                    "Set include_ignored=true to access it explicitly."
                ),
            )
        return resolved, None
