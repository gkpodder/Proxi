"""Smoke tests for proxi package."""

import proxi


def test_version() -> None:
    """Package exposes a version."""
    from pathlib import Path
    import re

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject_path.read_text(encoding="utf-8")
    parts = text.split("[project]")
    project_section = parts[1] if len(parts) > 1 else text
    m = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']\s*$', project_section)
    expected = m.group(1) if m else None
    assert expected is not None
    assert proxi.__version__ == expected


def test_imports() -> None:
    """Core modules import without error."""
    from proxi.core.state import AgentState, AgentStatus
    from proxi.workspace import WorkspaceManager

    assert AgentState is not None
    assert AgentStatus is not None
    assert WorkspaceManager is not None
