"""Memory schema: SQLite FTS5 for episodic memory, dataclasses for skills."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    summary     TEXT NOT NULL,
    full_text   TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    summary,
    full_text,
    tags,
    content=episodes,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS episodes_ai
AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, summary, full_text, tags)
    VALUES (new.id, new.summary, new.full_text, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodes_ad
AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, full_text, tags)
    VALUES ('delete', old.id, old.summary, old.full_text, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodes_au
AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, full_text, tags)
    VALUES ('delete', old.id, old.summary, old.full_text, old.tags);
    INSERT INTO episodes_fts(rowid, summary, full_text, tags)
    VALUES (new.id, new.summary, new.full_text, new.tags);
END;
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the memory SQLite database and apply the schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


@dataclass
class EpisodeSummary:
    """A single summarised past session stored in episodic memory."""

    agent_id: str
    session_id: str
    summary: str       # LLM-generated ~200 word summary
    full_text: str     # raw searchable content (messages + tool calls)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    id: int = 0


@dataclass
class SkillDoc:
    """An agentskills.io-compliant procedural skill document."""

    name: str
    description: str
    body: str                        # Markdown content (after frontmatter)
    compatibility: str = ""
    version: str = "1.0.0"
    created_by: str = "proxi"
    created_at: str = ""
    use_count: int = 0

    def to_skill_md(self) -> str:
        """Render the full SKILL.md content."""
        import json
        meta: dict[str, object] = {
            "version": self.version,
            "created_by": self.created_by,
            "use_count": self.use_count,
        }
        if self.created_at:
            meta["created_at"] = self.created_at
        # Build YAML frontmatter manually (no PyYAML dependency needed for simple values)
        meta_lines = "\n".join(f"  {k}: {json.dumps(v)}" for k, v in meta.items())
        lines = [
            "---",
            f"name: {self.name}",
            f"description: {self.description}",
        ]
        if self.compatibility:
            lines.append(f"compatibility: {self.compatibility}")
        lines += [
            "metadata:",
            meta_lines,
            "---",
            "",
            self.body.strip(),
            "",
        ]
        return "\n".join(lines)

    @classmethod
    def from_skill_md(cls, name: str, content: str) -> SkillDoc:
        """Parse a SKILL.md file back into a SkillDoc."""
        import json as _json
        lines = content.split("\n")
        if not lines or lines[0].strip() != "---":
            return cls(name=name, description="", body=content)

        # Find closing ---
        end = 1
        while end < len(lines) and lines[end].strip() != "---":
            end += 1

        frontmatter_lines = lines[1:end]
        body = "\n".join(lines[end + 1:]).strip()

        doc = cls(name=name, description="", body=body)
        in_metadata = False
        for line in frontmatter_lines:
            stripped = line.strip()
            if stripped == "metadata:":
                in_metadata = True
                continue
            if in_metadata:
                if line.startswith("  ") or line.startswith("\t"):
                    kv = stripped.split(":", 1)
                    if len(kv) == 2:
                        k, v = kv[0].strip(), kv[1].strip()
                        try:
                            parsed = _json.loads(v)
                        except Exception:
                            parsed = v.strip('"\'')
                        if k == "version":
                            doc.version = str(parsed)
                        elif k == "created_by":
                            doc.created_by = str(parsed)
                        elif k == "created_at":
                            doc.created_at = str(parsed)
                        elif k == "use_count":
                            try:
                                doc.use_count = int(parsed)
                            except Exception:
                                pass
                    continue
                else:
                    in_metadata = False
            kv = stripped.split(":", 1)
            if len(kv) == 2:
                k, v = kv[0].strip(), kv[1].strip()
                if k == "description":
                    doc.description = v
                elif k == "compatibility":
                    doc.compatibility = v
        return doc
