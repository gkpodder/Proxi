"""CLI wrapper for Obsidian MCP tool operations.

Exit code contract:
  0 - Script ran to completion. stdout is a JSON object.
      The JSON may contain an "error" key if the API reported a problem.
  1 - Unrecoverable script failure (bad args, import error, unexpected exception).
      stdout is a JSON object with "error" and "hint".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Obsidian operations via CLI",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-vaults", help="List vaults", allow_abbrev=False)

    list_notes = sub.add_parser("list-notes", help="List notes", allow_abbrev=False)
    list_notes.add_argument("--vault-name", default=None, help="Vault name")
    list_notes.add_argument("--vault-path", default=None, help="Vault path")
    list_notes.add_argument("--max-results", type=int, default=200, help="Max notes")

    read_note = sub.add_parser("read-note", help="Read note", allow_abbrev=False)
    read_note.add_argument("--vault-name", default=None, help="Vault name")
    read_note.add_argument("--vault-path", default=None, help="Vault path")
    read_note.add_argument("--note-path", required=True, help="Note path in vault")

    create_note = sub.add_parser("create-note", help="Create note", allow_abbrev=False)
    create_note.add_argument("--vault-name", default=None, help="Vault name")
    create_note.add_argument("--vault-path", default=None, help="Vault path")
    create_note.add_argument("--note-path", required=True, help="Note path in vault")
    create_note.add_argument("--content", required=True, help="Markdown content")
    create_note.add_argument("--overwrite", action="store_true", help="Overwrite existing")

    update_note = sub.add_parser("update-note", help="Update note", allow_abbrev=False)
    update_note.add_argument("--vault-name", default=None, help="Vault name")
    update_note.add_argument("--vault-path", default=None, help="Vault path")
    update_note.add_argument("--note-path", required=True, help="Note path in vault")
    update_note.add_argument("--content", required=True, help="Markdown content")
    update_note.add_argument("--append", action="store_true", help="Append content")

    search_notes = sub.add_parser("search-notes", help="Search notes", allow_abbrev=False)
    search_notes.add_argument("--vault-name", default=None, help="Vault name")
    search_notes.add_argument("--vault-path", default=None, help="Vault path")
    search_notes.add_argument("--query", required=True, help="Search text")
    search_notes.add_argument("--max-results", type=int, default=25, help="Max matches")

    metadata = sub.add_parser("get-note-metadata", help="Get note metadata", allow_abbrev=False)
    metadata.add_argument("--vault-name", default=None, help="Vault name")
    metadata.add_argument("--vault-path", default=None, help="Vault path")
    metadata.add_argument("--note-path", required=True, help="Note path in vault")

    args = parser.parse_args()

    try:
        from proxi.mcp.servers.obsidian_tools import ObsidianTools

        tools = ObsidianTools()

        if args.cmd == "list-vaults":
            result = asyncio.run(tools.list_vaults())
        elif args.cmd == "list-notes":
            result = asyncio.run(
                tools.list_notes(args.vault_name, args.vault_path, args.max_results)
            )
        elif args.cmd == "read-note":
            result = asyncio.run(
                tools.read_note(args.note_path, args.vault_name, args.vault_path)
            )
        elif args.cmd == "create-note":
            result = asyncio.run(
                tools.create_note(
                    args.note_path,
                    args.content,
                    args.vault_name,
                    args.vault_path,
                    args.overwrite,
                )
            )
        elif args.cmd == "update-note":
            result = asyncio.run(
                tools.update_note(
                    args.note_path,
                    args.content,
                    args.vault_name,
                    args.vault_path,
                    args.append,
                )
            )
        elif args.cmd == "search-notes":
            result = asyncio.run(
                tools.search_notes(
                    args.query,
                    args.vault_name,
                    args.vault_path,
                    args.max_results,
                )
            )
        else:
            result = asyncio.run(
                tools.get_note_metadata(args.note_path, args.vault_name, args.vault_path)
            )

        print(json.dumps(result))
        sys.exit(0)

    except Exception as e:
        print(
            json.dumps(
                {
                    "error": str(e),
                    "hint": (
                        "This is a script-level failure, not an API error. "
                        "Check Obsidian vault configuration and inputs."
                    ),
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
