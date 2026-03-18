"""SQLite-backed API key storage for Proxi."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from proxi.mcp.catalog import known_mcp_categories

DEFAULT_DB_PATH = Path(os.getenv("PROXI_KEYS_DB_PATH", "config/api_keys.db"))


@dataclass(slots=True)
class ApiKeyRecord:
    key_name: str
    key_value: str
    updated_at: str


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve the SQLite DB path and ensure parent directory exists."""
    target = Path(db_path) if db_path else DEFAULT_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a sqlite3 connection with row factory."""
    conn = sqlite3.connect(resolve_db_path(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path | None = None) -> Path:
    """Create the API keys and enabled_mcps tables if they do not exist."""
    db_file = resolve_db_path(db_path)
    with get_connection(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key_name TEXT PRIMARY KEY,
                key_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS enabled_mcps (
                mcp_name TEXT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    return db_file


def upsert_key(key_name: str, key_value: str, db_path: str | Path | None = None) -> None:
    """Insert or update a key in the key store."""
    normalized_name = key_name.strip().upper()
    if not normalized_name:
        raise ValueError("Key name cannot be empty")
    if not key_value:
        raise ValueError("Key value cannot be empty")

    now = datetime.now(UTC).isoformat()
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO api_keys (key_name, key_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key_name) DO UPDATE SET
                key_value = excluded.key_value,
                updated_at = excluded.updated_at
            """,
            (normalized_name, key_value, now),
        )
        conn.commit()


def get_key(key_name: str, db_path: str | Path | None = None) -> ApiKeyRecord | None:
    """Retrieve one key record by name."""
    normalized_name = key_name.strip().upper()
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT key_name, key_value, updated_at FROM api_keys WHERE key_name = ?",
            (normalized_name,),
        ).fetchone()
    if not row:
        return None
    return ApiKeyRecord(row["key_name"], row["key_value"], row["updated_at"])


def list_keys(db_path: str | Path | None = None) -> list[ApiKeyRecord]:
    """List all key records sorted by key name."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT key_name, key_value, updated_at FROM api_keys ORDER BY key_name"
        ).fetchall()
    return [ApiKeyRecord(row["key_name"], row["key_value"], row["updated_at"]) for row in rows]


def get_key_value(key_name: str, db_path: str | Path | None = None) -> str | None:
    """Return only the key value for application use."""
    record = get_key(key_name, db_path=db_path)
    if not record:
        return None
    return record.key_value


def export_env_keys(db_path: str | Path | None = None) -> dict[str, str]:
    """Export all stored keys as environment variable mappings."""
    exported: dict[str, str] = {}
    for record in list_keys(db_path=db_path):
        if record.key_value:
            exported[record.key_name] = record.key_value
    return exported


def _mask_key(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


# MCP Management Functions

@dataclass(slots=True)
class MCPRecord:
    mcp_name: str
    enabled: bool
    created_at: str


def enable_mcp(mcp_name: str, enabled: bool = True, db_path: str | Path | None = None) -> None:
    """Enable or disable an MCP."""
    normalized_name = mcp_name.strip().lower()
    if not normalized_name:
        raise ValueError("MCP name cannot be empty")

    now = datetime.now(UTC).isoformat()
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO enabled_mcps (mcp_name, enabled, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(mcp_name) DO UPDATE SET
                enabled = excluded.enabled
            """,
            (normalized_name, enabled, now),
        )
        conn.commit()


def is_mcp_enabled(mcp_name: str, db_path: str | Path | None = None) -> bool:
    """Check if an MCP is enabled."""
    normalized_name = mcp_name.strip().lower()
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT enabled FROM enabled_mcps WHERE mcp_name = ?",
            (normalized_name,),
        ).fetchone()
    if not row:
        return False
    return bool(row["enabled"])


def list_mcps(db_path: str | Path | None = None) -> list[MCPRecord]:
    """List MCP records sorted by name, including known MCPs not yet persisted."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT mcp_name, enabled, created_at FROM enabled_mcps ORDER BY mcp_name"
        ).fetchall()

    records: dict[str, MCPRecord] = {
        row["mcp_name"]: MCPRecord(row["mcp_name"], bool(row["enabled"]), row["created_at"])
        for row in rows
    }

    for mcp_name in known_mcp_categories():
        if mcp_name not in records:
            records[mcp_name] = MCPRecord(mcp_name=mcp_name, enabled=False, created_at="")

    return [records[name] for name in sorted(records.keys())]


def get_enabled_mcps(db_path: str | Path | None = None) -> list[str]:
    """Get list of enabled MCP names."""
    return [mcp.mcp_name for mcp in list_mcps(db_path) if mcp.enabled]



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Proxi API keys and MCPs in SQLite")
    parser.add_argument("--db", help="Override SQLite database path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the key store database")

    list_parser = subparsers.add_parser("list", help="List stored key metadata")
    list_parser.add_argument(
        "--show-values",
        action="store_true",
        help="Include full key values in output (use carefully)",
    )

    get_parser = subparsers.add_parser("get", help="Get one key")
    get_parser.add_argument("--key", required=True, help="Environment-style key name")

    upsert_parser = subparsers.add_parser("upsert", help="Insert or update one key")
    upsert_parser.add_argument("--key", required=True, help="Environment-style key name")
    upsert_parser.add_argument("--value", required=True, help="Secret value")

    subparsers.add_parser("export-env", help="Export all keys as JSON object")

    # MCP subcommands
    list_mcps_parser = subparsers.add_parser("list-mcps", help="List all MCPs and their status")

    enable_mcp_parser = subparsers.add_parser("enable-mcp", help="Enable an MCP")
    enable_mcp_parser.add_argument("mcp_name", help="MCP name (e.g., gmail, calendar, notion, weather)")

    disable_mcp_parser = subparsers.add_parser("disable-mcp", help="Disable an MCP")
    disable_mcp_parser.add_argument("mcp_name", help="MCP name (e.g., gmail, calendar, notion, weather)")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = args.db

    try:
        if args.command == "init":
            db_file = init_db(db_path)
            print(json.dumps({"ok": True, "db_path": str(db_file)}))
            return 0

        if args.command == "list":
            records = list_keys(db_path)
            output = []
            for record in records:
                item = {
                    "key_name": record.key_name,
                    "updated_at": record.updated_at,
                    "masked_value": _mask_key(record.key_value),
                }
                if args.show_values:
                    item["value"] = record.key_value
                output.append(item)
            print(json.dumps({"ok": True, "keys": output}))
            return 0

        if args.command == "get":
            record = get_key(args.key, db_path)
            if not record:
                print(json.dumps({"ok": False, "error": "Key not found"}))
                return 1
            print(
                json.dumps(
                    {
                        "ok": True,
                        "key": {
                            "key_name": record.key_name,
                            "updated_at": record.updated_at,
                            "masked_value": _mask_key(record.key_value),
                            "value": record.key_value,
                        },
                    }
                )
            )
            return 0

        if args.command == "upsert":
            upsert_key(args.key, args.value, db_path)
            print(json.dumps({"ok": True, "key_name": args.key.strip().upper()}))
            return 0

        if args.command == "export-env":
            print(json.dumps({"ok": True, "env": export_env_keys(db_path)}))
            return 0

        if args.command == "list-mcps":
            records = list_mcps(db_path)
            output = [
                {"mcp_name": r.mcp_name, "enabled": r.enabled, "created_at": r.created_at}
                for r in records
            ]
            print(json.dumps({"ok": True, "mcps": output}))
            return 0

        if args.command == "enable-mcp":
            enable_mcp(args.mcp_name, enabled=True, db_path=db_path)
            print(json.dumps({"ok": True, "mcp_name": args.mcp_name.strip().lower(), "enabled": True}))
            return 0

        if args.command == "disable-mcp":
            enable_mcp(args.mcp_name, enabled=False, db_path=db_path)
            print(json.dumps({"ok": True, "mcp_name": args.mcp_name.strip().lower(), "enabled": False}))
            return 0

    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
