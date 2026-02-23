"""Smoke tests for proxi package."""

import pytest

import proxi


def test_version() -> None:
    """Package exposes a version."""
    assert proxi.__version__ == "0.1.0"


def test_imports() -> None:
    """Core modules import without error."""
    from proxi.core.state import AgentState, AgentStatus
    from proxi.workspace import WorkspaceManager

    assert AgentState is not None
    assert AgentStatus is not None
    assert WorkspaceManager is not None
