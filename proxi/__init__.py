"""Proxi - A general-purpose agent loop with multi-agent orchestration."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path


def _read_version_from_pyproject() -> str | None:
    """Best-effort extraction of `version` from the `[project]` table."""
    try:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        text = pyproject_path.read_text(encoding="utf-8")
    except Exception:
        return None

    # Keep it simple: split on the first `[project]` table and parse the first `version = ...` line.
    parts = text.split("[project]")
    project_section = parts[1] if len(parts) > 1 else text
    m = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']\s*$', project_section)
    return m.group(1) if m else None


try:
    # Prefer installed package metadata when available.
    __version__ = pkg_version("proxi")
except PackageNotFoundError:
    __version__ = _read_version_from_pyproject() or "0.0.0"
