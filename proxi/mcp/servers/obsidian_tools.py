"""Obsidian vault tools for MCP server."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

from proxi.observability.logging import get_logger
from proxi.security.key_store import get_key_value

logger = get_logger(__name__)

load_dotenv()


class ObsidianTools:
    """Tools for interacting with local Obsidian vaults."""

    def __init__(self) -> None:
        """Initialize Obsidian tools and discover available vaults."""
        self._vaults = self._discover_vaults()
        logger.info("obsidian_vaults_discovered", count=len(self._vaults))

    def _discover_vaults(self) -> dict[str, Path]:
        """Discover Obsidian vaults from env vars and Obsidian config."""
        vaults: dict[str, Path] = {}
        configured_paths = self._configured_vault_paths()

        for path in configured_paths:
            if path.is_dir():
                vaults[path.name] = path

        for name, path in self._vaults_from_obsidian_config().items():
            if path.is_dir():
                vaults.setdefault(name, path)

        return vaults

    @staticmethod
    def _normalize_config_value(raw_value: str) -> str:
        """Normalize configured path values (quotes, file:// URI, whitespace)."""
        value = raw_value.strip()
        if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
            value = value[1:-1].strip()

        if value.lower().startswith("file://"):
            parsed = urlparse(value)
            uri_path = unquote(parsed.path or "")

            # file://localhost/path and file:///path are equivalent local paths.
            if parsed.netloc and parsed.netloc not in ("", "localhost"):
                uri_path = f"//{parsed.netloc}{uri_path}"

            # Windows file URI often prefixes local drive letter paths with '/'.
            if os.name == "nt" and len(uri_path) >= 3 and uri_path[0] == "/" and uri_path[2] == ":":
                uri_path = uri_path[1:]

            value = uri_path

        return value.strip()

    def _get_config_value(self, key: str) -> str:
        """Resolve a config value from the SQLite key store only."""
        db_value = get_key_value(key)
        if db_value and db_value.strip():
            return db_value.strip()

        return ""

    def _configured_vault_paths(self) -> list[Path]:
        """Collect configured vault paths from single and multi-value settings."""
        resolved_paths: list[Path] = []
        seen: set[str] = set()

        single_path = self._get_config_value("OBSIDIAN_VAULT_PATH")
        if single_path:
            normalized = self._normalize_config_value(single_path)
            if normalized:
                path = Path(normalized).expanduser().resolve()
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    resolved_paths.append(path)

        multi_raw = self._get_config_value("OBSIDIAN_VAULT_PATHS")
        if not multi_raw:
            return resolved_paths

        raw_candidates: list[str] = []
        try:
            parsed = json.loads(multi_raw)
            if isinstance(parsed, list):
                raw_candidates.extend(str(item) for item in parsed)
            elif isinstance(parsed, str):
                raw_candidates.append(parsed)
        except json.JSONDecodeError:
            for separator in ("\n", ",", os.pathsep):
                if separator in multi_raw:
                    raw_candidates.extend(part for part in multi_raw.split(separator))
                    break
            if not raw_candidates:
                raw_candidates.append(multi_raw)

        for candidate in raw_candidates:
            normalized = self._normalize_config_value(candidate)
            if not normalized:
                continue
            path = Path(normalized).expanduser().resolve()
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            resolved_paths.append(path)

        return resolved_paths

    def _vaults_from_obsidian_config(self) -> dict[str, Path]:
        """Read known vaults from Obsidian desktop config when available."""
        config_paths = self._obsidian_config_candidates()
        for config_path in config_paths:
            if not config_path.exists():
                continue
            try:
                with open(config_path, "r", encoding="utf-8") as file:
                    payload = json.load(file)

                raw_vaults = payload.get("vaults", {})
                if not isinstance(raw_vaults, dict):
                    continue

                resolved: dict[str, Path] = {}
                for entry in raw_vaults.values():
                    if not isinstance(entry, dict):
                        continue
                    raw_path = entry.get("path")
                    if not isinstance(raw_path, str) or not raw_path.strip():
                        continue
                    path = Path(raw_path).expanduser().resolve()
                    if path.is_dir():
                        resolved[path.name] = path

                if resolved:
                    return resolved
            except Exception as exc:
                logger.warning("obsidian_config_parse_error", path=str(config_path), error=str(exc))

        return {}

    def _obsidian_config_candidates(self) -> list[Path]:
        """Build platform-aware candidate paths for obsidian.json."""
        candidates: list[Path] = []

        appdata = os.getenv("APPDATA")
        if appdata:
            appdata_path = Path(appdata)
            candidates.extend(
                [
                    appdata_path / "Obsidian" / "obsidian.json",
                    appdata_path / "obsidian" / "obsidian.json",
                ]
            )

        home = Path.home()
        system_name = platform.system().lower()
        if system_name == "darwin":
            mac_support = home / "Library" / "Application Support"
            candidates.extend(
                [
                    mac_support / "obsidian" / "obsidian.json",
                    mac_support / "Obsidian" / "obsidian.json",
                ]
            )

        # Fallbacks for non-standard setups.
        candidates.extend(
            [
                home / ".config" / "obsidian" / "obsidian.json",
                home / ".obsidian" / "obsidian.json",
            ]
        )

        seen: set[str] = set()
        deduped: list[Path] = []
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _resolve_vault(
        self,
        vault_name: str | None = None,
        vault_path: str | None = None,
    ) -> tuple[str, Path]:
        """Resolve a target vault from explicit path/name or discovered defaults."""
        if vault_path and vault_path.strip():
            path = Path(vault_path).expanduser().resolve()
            if not path.is_dir():
                raise ValueError(f"Vault path does not exist: {path}")
            return (vault_name or path.name, path)

        if vault_name and vault_name in self._vaults:
            return (vault_name, self._vaults[vault_name])

        if vault_name:
            available = sorted(self._vaults.keys())
            raise ValueError(
                f"Unknown vault '{vault_name}'. Available vaults: {available}"
            )

        if len(self._vaults) == 1:
            name, path = next(iter(self._vaults.items()))
            return (name, path)

        if not self._vaults:
            raise ValueError(
                "No Obsidian vaults found. Save OBSIDIAN_VAULT_PATH/OBSIDIAN_VAULT_PATHS "
                "in the SQLite key store, or open Obsidian to initialize obsidian.json."
            )

        raise ValueError(
            "Multiple vaults found. Provide vault_name or vault_path to choose one."
        )

    @staticmethod
    def _resolve_note_path(vault_root: Path, note_path: str) -> Path:
        """Resolve and validate a note path inside a vault root."""
        raw_note_path = note_path.strip()
        if not raw_note_path:
            raise ValueError("note_path cannot be empty")

        note_candidate = Path(raw_note_path)
        if note_candidate.suffix.lower() != ".md":
            note_candidate = note_candidate.with_suffix(".md")

        full_path = (vault_root / note_candidate).resolve()
        try:
            full_path.relative_to(vault_root)
        except ValueError as exc:
            raise ValueError("note_path must stay inside the selected vault") from exc
        return full_path

    @staticmethod
    def _extract_frontmatter(content: str) -> dict[str, Any]:
        """Extract a simple key-value frontmatter map from markdown content."""
        if not content.startswith("---\n"):
            return {}

        lines = content.splitlines()
        if len(lines) < 3:
            return {}

        metadata: dict[str, Any] = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
        return metadata

    async def list_vaults(self) -> dict[str, Any]:
        """List discovered Obsidian vaults."""
        items = [
            {"name": name, "path": str(path)}
            for name, path in sorted(self._vaults.items(), key=lambda item: item[0].lower())
        ]
        return {"vaults": items, "count": len(items)}

    async def list_notes(
        self,
        vault_name: str | None = None,
        vault_path: str | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List markdown notes in a selected Obsidian vault."""
        name, root = self._resolve_vault(vault_name=vault_name, vault_path=vault_path)

        limit = max(1, min(max_results, 2000))
        notes: list[dict[str, Any]] = []

        for path in sorted(root.rglob("*.md")):
            if ".obsidian" in path.parts:
                continue
            relative = str(path.relative_to(root)).replace("\\", "/")
            notes.append(
                {
                    "path": relative,
                    "name": path.stem,
                    "size_bytes": path.stat().st_size,
                }
            )
            if len(notes) >= limit:
                break

        return {
            "vault": {"name": name, "path": str(root)},
            "notes": notes,
            "count": len(notes),
            "max_results": limit,
        }

    async def read_note(
        self,
        note_path: str,
        vault_name: str | None = None,
        vault_path: str | None = None,
    ) -> dict[str, Any]:
        """Read a markdown note from a selected Obsidian vault."""
        name, root = self._resolve_vault(vault_name=vault_name, vault_path=vault_path)
        note_file = self._resolve_note_path(root, note_path)
        if not note_file.exists():
            raise ValueError(f"Note not found: {note_path}")

        with open(note_file, "r", encoding="utf-8") as file:
            content = file.read()

        return {
            "vault": {"name": name, "path": str(root)},
            "note": str(note_file.relative_to(root)).replace("\\", "/"),
            "content": content,
        }

    async def create_note(
        self,
        note_path: str,
        content: str,
        vault_name: str | None = None,
        vault_path: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Create a markdown note in a selected Obsidian vault."""
        name, root = self._resolve_vault(vault_name=vault_name, vault_path=vault_path)
        note_file = self._resolve_note_path(root, note_path)

        if note_file.exists() and not overwrite:
            raise ValueError(
                "Note already exists. Set overwrite=true to replace existing content."
            )

        note_file.parent.mkdir(parents=True, exist_ok=True)
        with open(note_file, "w", encoding="utf-8") as file:
            file.write(content)

        return {
            "vault": {"name": name, "path": str(root)},
            "note": str(note_file.relative_to(root)).replace("\\", "/"),
            "created": True,
            "bytes_written": len(content.encode("utf-8")),
        }

    async def update_note(
        self,
        note_path: str,
        content: str,
        vault_name: str | None = None,
        vault_path: str | None = None,
        append: bool = False,
    ) -> dict[str, Any]:
        """Update an existing markdown note in a selected Obsidian vault."""
        name, root = self._resolve_vault(vault_name=vault_name, vault_path=vault_path)
        note_file = self._resolve_note_path(root, note_path)
        if not note_file.exists():
            raise ValueError(f"Note not found: {note_path}")

        mode = "a" if append else "w"
        with open(note_file, mode, encoding="utf-8") as file:
            file.write(content)

        return {
            "vault": {"name": name, "path": str(root)},
            "note": str(note_file.relative_to(root)).replace("\\", "/"),
            "updated": True,
            "append": append,
            "bytes_written": len(content.encode("utf-8")),
        }

    async def search_notes(
        self,
        query: str,
        vault_name: str | None = None,
        vault_path: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """Search markdown notes in a selected Obsidian vault by substring."""
        name, root = self._resolve_vault(vault_name=vault_name, vault_path=vault_path)
        term = query.strip().lower()
        if not term:
            raise ValueError("query cannot be empty")

        limit = max(1, min(max_results, 500))
        matches: list[dict[str, Any]] = []

        for path in sorted(root.rglob("*.md")):
            if ".obsidian" in path.parts:
                continue
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()

            content_lower = content.lower()
            idx = content_lower.find(term)
            if idx == -1:
                continue

            start = max(0, idx - 80)
            end = min(len(content), idx + len(term) + 80)
            snippet = content[start:end].replace("\n", " ").strip()
            matches.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "snippet": snippet,
                }
            )
            if len(matches) >= limit:
                break

        return {
            "vault": {"name": name, "path": str(root)},
            "query": query,
            "matches": matches,
            "count": len(matches),
            "max_results": limit,
        }

    async def get_note_metadata(
        self,
        note_path: str,
        vault_name: str | None = None,
        vault_path: str | None = None,
    ) -> dict[str, Any]:
        """Get basic note metadata, including simple frontmatter key-values."""
        name, root = self._resolve_vault(vault_name=vault_name, vault_path=vault_path)
        note_file = self._resolve_note_path(root, note_path)
        if not note_file.exists():
            raise ValueError(f"Note not found: {note_path}")

        with open(note_file, "r", encoding="utf-8") as file:
            content = file.read()

        stat = note_file.stat()
        return {
            "vault": {"name": name, "path": str(root)},
            "note": str(note_file.relative_to(root)).replace("\\", "/"),
            "metadata": {
                "size_bytes": stat.st_size,
                "modified_time": stat.st_mtime,
                "frontmatter": self._extract_frontmatter(content),
            },
        }
