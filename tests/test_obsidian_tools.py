"""Tests for Obsidian vault discovery and config normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proxi.mcp.servers import obsidian_tools as obsidian_module
from proxi.mcp.servers.obsidian_tools import ObsidianTools


def test_discovers_vault_from_db_single_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falls back to SQLite key store when env values are not provided."""
    vault = tmp_path / "VaultFromDb"
    vault.mkdir()

    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATHS", raising=False)
    monkeypatch.setattr(
        obsidian_module,
        "get_key_value",
        lambda key: str(vault) if key == "OBSIDIAN_VAULT_PATH" else None,
    )
    monkeypatch.setattr(ObsidianTools, "_vaults_from_obsidian_config", lambda self: {})

    tools = ObsidianTools()
    assert tools._vaults.get(vault.name) == vault.resolve()


def test_ignores_env_vault_path_uses_db_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment variables are ignored for vault config discovery."""
    env_vault = tmp_path / "EnvVault"
    db_vault = tmp_path / "DbVault"
    env_vault.mkdir()
    db_vault.mkdir()

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(env_vault))
    monkeypatch.delenv("OBSIDIAN_VAULT_PATHS", raising=False)
    monkeypatch.setattr(
        obsidian_module,
        "get_key_value",
        lambda key: str(db_vault) if key == "OBSIDIAN_VAULT_PATH" else None,
    )
    monkeypatch.setattr(ObsidianTools, "_vaults_from_obsidian_config", lambda self: {})

    tools = ObsidianTools()
    assert tools._vaults.get(db_vault.name) == db_vault.resolve()
    assert env_vault.name not in tools._vaults


def test_discovers_vaults_from_db_multi_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supports JSON array values for OBSIDIAN_VAULT_PATHS in key store."""
    first = tmp_path / "FirstVault"
    second = tmp_path / "SecondVault"
    first.mkdir()
    second.mkdir()

    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATHS", raising=False)

    values = {
        "OBSIDIAN_VAULT_PATHS": json.dumps([str(first), str(second)]),
    }
    monkeypatch.setattr(
        obsidian_module,
        "get_key_value",
        lambda key: values.get(key),
    )
    monkeypatch.setattr(ObsidianTools, "_vaults_from_obsidian_config", lambda self: {})

    tools = ObsidianTools()
    assert tools._vaults.get(first.name) == first.resolve()
    assert tools._vaults.get(second.name) == second.resolve()


def test_discovers_vault_from_file_uri_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalizes file:// URIs in DB-backed path config values."""
    vault = tmp_path / "VaultFromUri"
    vault.mkdir()

    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATHS", raising=False)
    monkeypatch.setattr(
        obsidian_module,
        "get_key_value",
        lambda key: f'"{vault.as_uri()}"' if key == "OBSIDIAN_VAULT_PATH" else None,
    )
    monkeypatch.setattr(ObsidianTools, "_vaults_from_obsidian_config", lambda self: {})

    tools = ObsidianTools()
    assert tools._vaults.get(vault.name) == vault.resolve()
