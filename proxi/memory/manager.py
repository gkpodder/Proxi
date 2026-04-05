"""MemoryManager: central interface for procedural, episodic, and user model memory."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from proxi.memory.schema import EpisodeSummary, SkillDoc, init_db
from proxi.observability.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_USER_MD_TEMPLATE = """\
## Preferences

## Communication Style

## Environment

## Coding Conventions

## Relationships
"""

# Maximum character length of USER.md (~600 tokens ≈ 2400 chars)
_USER_MD_MAX_CHARS = 2400


class MemoryManager:
    """Central interface for all memory operations.

    Initialized once at gateway startup and shared across agent lanes.
    All blocking SQLite I/O is run in a thread-pool executor so it
    does not block the asyncio event loop.
    """

    def __init__(self, memory_dir: Path, gateway_config_path: Path | None = None) -> None:
        self.memory_dir = memory_dir
        self.skills_dir = memory_dir / "skills"
        self.user_md_path = memory_dir / "USER.md"
        self._db_path = memory_dir / "memory.db"
        self._gateway_config_path = gateway_config_path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Initialize directories and database (call once at startup)."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._conn = init_db(self._db_path)
        if not self.user_md_path.exists():
            self.user_md_path.write_text(_USER_MD_TEMPLATE, encoding="utf-8")
        logger.info("memory_manager_initialized",
                    memory_dir=str(self.memory_dir))

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Enable / disable per agent
    # ------------------------------------------------------------------

    def is_enabled(self, agent_id: str) -> bool:
        """Return True if memory is enabled for this agent (default: True).

        Reads from gateway.yml:
            agents:
              <agent_id>:
                memory:
                  enabled: false
        """
        if self._gateway_config_path is None or not self._gateway_config_path.exists():
            return True
        try:
            import yaml  # type: ignore[import-untyped]
            raw = yaml.safe_load(
                self._gateway_config_path.read_text(encoding="utf-8"))
            agent_cfg = (raw or {}).get("agents", {}).get(agent_id, {})
            memory_cfg = agent_cfg.get("memory", {})
            if isinstance(memory_cfg, dict):
                return bool(memory_cfg.get("enabled", True))
        except Exception:
            pass
        return True

    # ------------------------------------------------------------------
    # Episodic memory
    # ------------------------------------------------------------------

    async def save_episode(self, episode: EpisodeSummary) -> None:
        """Persist a session summary to the episodic FTS5 database."""
        if self._conn is None:
            return
        now = episode.created_at or datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(episode.tags)

        loop = asyncio.get_event_loop()
        async with self._lock:
            await loop.run_in_executor(
                None,
                self._insert_episode,
                episode.agent_id,
                episode.session_id,
                episode.summary,
                episode.full_text,
                tags_json,
                now,
            )

    def _insert_episode(
        self,
        agent_id: str,
        session_id: str,
        summary: str,
        full_text: str,
        tags_json: str,
        created_at: str,
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO episodes (agent_id, session_id, summary, full_text, tags, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, session_id, summary, full_text, tags_json, created_at),
        )
        self._conn.commit()

    async def search_episodes(self, query: str, limit: int = 5) -> list[EpisodeSummary]:
        """FTS5 full-text search over past session summaries."""
        if self._conn is None or not query.strip():
            return []
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, self._fts_search_episodes, query, limit)
        results: list[EpisodeSummary] = []
        for row in rows:
            try:
                tags = json.loads(row["tags"] or "[]")
            except Exception:
                tags = []
            results.append(
                EpisodeSummary(
                    id=row["id"],
                    agent_id=row["agent_id"],
                    session_id=row["session_id"],
                    summary=row["summary"],
                    full_text=row["full_text"],
                    tags=tags,
                    created_at=row["created_at"],
                )
            )
        return results

    def _fts_search_episodes(self, query: str, limit: int) -> list[sqlite3.Row]:
        assert self._conn is not None
        # Sanitise the query: strip special FTS5 operators that could cause syntax errors
        safe_query = query.replace('"', "").replace(
            "*", "").replace("^", "").strip()
        if not safe_query:
            return []
        try:
            cur = self._conn.execute(
                """
                SELECT e.id, e.agent_id, e.session_id, e.summary, e.full_text, e.tags, e.created_at
                FROM episodes e
                JOIN episodes_fts ON episodes_fts.rowid = e.id
                WHERE episodes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, limit),
            )
            return cur.fetchall()
        except sqlite3.OperationalError:
            return []

    # ------------------------------------------------------------------
    # Skill (procedural) memory
    # ------------------------------------------------------------------

    async def search_skills(self, query: str, limit: int = 3) -> list[SkillDoc]:
        """Search skill library by name + description keyword matching."""
        if not query.strip():
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_skills_sync, query, limit)

    def _search_skills_sync(self, query: str, limit: int) -> list[SkillDoc]:
        skills: list[tuple[int, SkillDoc]] = []  # (match_score, doc)
        query_lower = query.lower()
        terms = query_lower.split()
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                doc = SkillDoc.from_skill_md(skill_dir.name, content)
                # Simple term-frequency scoring
                text = (doc.name + " " + doc.description +
                        " " + doc.body).lower()
                score = sum(text.count(t) for t in terms)
                if score > 0:
                    skills.append((score, doc))
            except Exception:
                continue
        skills.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in skills[:limit]]

    async def save_skill(self, doc: SkillDoc) -> None:
        """Create or patch a SKILL.md in the skill library."""
        if not doc.name:
            return
        # Sanitise name: lowercase, hyphens only
        safe_name = doc.name.lower().replace(" ", "-").replace("_", "-")
        doc = SkillDoc(
            name=safe_name,
            description=doc.description,
            body=doc.body,
            compatibility=doc.compatibility,
            version=doc.version,
            created_by=doc.created_by,
            created_at=doc.created_at or datetime.now(
                timezone.utc).date().isoformat(),
            use_count=doc.use_count,
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_skill_sync, doc)

    def _save_skill_sync(self, doc: SkillDoc) -> None:
        skill_dir = self.skills_dir / doc.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"

        if skill_md.exists():
            # Patch: bump version, update sections that appear in new body
            existing = SkillDoc.from_skill_md(
                doc.name, skill_md.read_text(encoding="utf-8"))
            doc = _patch_skill(existing, doc)

        skill_md.write_text(doc.to_skill_md(), encoding="utf-8")
        logger.info("skill_saved", name=doc.name, version=doc.version)

    async def increment_skill_use_count(self, skill_name: str) -> None:
        """Bump the use_count for a skill when it is retrieved."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._increment_use_count_sync, skill_name)

    def _increment_use_count_sync(self, skill_name: str) -> None:
        safe_name = skill_name.lower().replace(" ", "-").replace("_", "-")
        skill_md = self.skills_dir / safe_name / "SKILL.md"
        if not skill_md.exists():
            return
        try:
            content = skill_md.read_text(encoding="utf-8")
            doc = SkillDoc.from_skill_md(safe_name, content)
            doc.use_count += 1
            skill_md.write_text(doc.to_skill_md(), encoding="utf-8")
        except Exception:
            pass

    def list_skills(self) -> list[str]:
        """Return skill names available in the library."""
        names = []
        for d in self.skills_dir.iterdir():
            if d.is_dir() and (d / "SKILL.md").exists():
                names.append(d.name)
        return sorted(names)

    # ------------------------------------------------------------------
    # User model
    # ------------------------------------------------------------------

    def get_user_model(self) -> str:
        """Read USER.md content."""
        if not self.user_md_path.exists():
            return ""
        return self.user_md_path.read_text(encoding="utf-8").strip()

    async def update_user_model(self, patch: str) -> None:
        """Replace one or more sections in USER.md.

        *patch* should be valid markdown with ## section headers.
        Each section in *patch* replaces the matching section in USER.md.
        Sections not present in *patch* are left untouched.
        New sections in *patch* that don't exist yet are appended.
        """
        loop = asyncio.get_event_loop()
        async with self._lock:
            await loop.run_in_executor(None, self._update_user_model_sync, patch)

    def _update_user_model_sync(self, patch: str) -> None:
        current = self.user_md_path.read_text(
            encoding="utf-8") if self.user_md_path.exists() else _USER_MD_TEMPLATE
        updated = _merge_sections(current, patch)
        # Enforce max length
        if len(updated) > _USER_MD_MAX_CHARS:
            updated = updated[:_USER_MD_MAX_CHARS]
        self.user_md_path.write_text(updated, encoding="utf-8")
        logger.info("user_model_updated")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _split_sections(text: str) -> dict[str, str]:
    """Split markdown into {section_header: content} mapping."""
    sections: dict[str, str] = {}
    current_header: str | None = None
    current_lines: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if current_header is not None:
                sections[current_header] = "\n".join(current_lines).rstrip()
            current_header = line
            current_lines = []
        else:
            current_lines.append(line)
    if current_header is not None:
        sections[current_header] = "\n".join(current_lines).rstrip()
    return sections


def _merge_sections(base: str, patch: str) -> str:
    """Merge patch sections into base, preserving non-patched sections."""
    base_sections = _split_sections(base)
    patch_sections = _split_sections(patch)

    # Update/add sections from patch
    for header, content in patch_sections.items():
        base_sections[header] = content

    # Reconstruct — preserve original order for existing sections, append new ones
    seen: set[str] = set()
    parts: list[str] = []
    for header in list(_split_sections(base).keys()):
        if header in base_sections:
            parts.append(header)
            body = base_sections[header]
            if body:
                parts.append(body)
            seen.add(header)
    # Append new sections from patch
    for header in patch_sections:
        if header not in seen:
            parts.append(header)
            body = base_sections[header]
            if body:
                parts.append(body)

    return "\n\n".join(parts) + "\n"


def _bump_patch_version(version: str) -> str:
    """Bump the patch component of a semver string (e.g. '1.0.2' → '1.0.3')."""
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        return version
    return ".".join(parts)


def _patch_skill(existing: SkillDoc, new: SkillDoc) -> SkillDoc:
    """Merge new skill content into existing, patching body sections and bumping version."""
    merged_body = _merge_markdown_sections(existing.body, new.body)
    return SkillDoc(
        name=existing.name,
        description=new.description or existing.description,
        body=merged_body,
        compatibility=new.compatibility or existing.compatibility,
        version=_bump_patch_version(existing.version),
        created_by=existing.created_by,
        created_at=existing.created_at,
        use_count=existing.use_count,
    )


def _merge_markdown_sections(base: str, patch: str) -> str:
    """Merge patch's ## sections into base body (used for skill body patching)."""
    # Simple approach: collect ## sections from patch, replace in base
    base_sections: dict[str, str] = {}
    order: list[str] = []
    current: str | None = None
    lines: list[str] = []
    for line in base.split("\n"):
        if line.startswith("## "):
            if current is not None:
                base_sections[current] = "\n".join(lines).rstrip()
            current = line
            order.append(current)
            lines = []
        else:
            lines.append(line)
    if current is not None:
        base_sections[current] = "\n".join(lines).rstrip()

    # Parse patch sections
    patch_sections: dict[str, str] = {}
    current = None
    lines = []
    for line in patch.split("\n"):
        if line.startswith("## "):
            if current is not None:
                patch_sections[current] = "\n".join(lines).rstrip()
            current = line
            lines = []
        else:
            lines.append(line)
    if current is not None:
        patch_sections[current] = "\n".join(lines).rstrip()

    # If patch has no sections, replace entire body
    if not patch_sections:
        return patch.strip()

    # Merge
    for header, content in patch_sections.items():
        base_sections[header] = content
        if header not in order:
            order.append(header)

    parts: list[str] = []
    for h in order:
        parts.append(h)
        body = base_sections.get(h, "")
        if body:
            parts.append(body)
    return "\n\n".join(parts)
