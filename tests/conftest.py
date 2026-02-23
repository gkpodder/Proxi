"""Pytest configuration and fixtures for proxi tests."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_proxi_root(tmp_path: Path) -> Path:
    """Temporary directory for proxi workspace (replaces ~/.proxi)."""
    return tmp_path


@pytest.fixture
def proxi_home_env(tmp_proxi_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set PROXI_HOME to a temp dir for isolated workspace tests."""
    monkeypatch.setenv("PROXI_HOME", str(tmp_proxi_root))
    return tmp_proxi_root
