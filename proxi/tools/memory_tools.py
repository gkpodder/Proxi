"""Memory tools: search_memory, save_skill, update_user_model."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from proxi.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from proxi.memory.manager import MemoryManager


class SearchMemoryTool(BaseTool):
    """FTS5 search over past episodes and the skill library."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        super().__init__(
            name="search_memory",
            description=(
                "Search your persistent memory for relevant past sessions (episodic) "
                "and reusable skill workflows (procedural). "
                "Use this when the user references a past task, a recurring workflow, "
                "or when you want to check if a how-to procedure already exists."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords or natural language query to search memory.",
                    },
                    "max_episodes": {
                        "type": "integer",
                        "description": "Maximum number of past episodes to return (default 5).",
                        "default": 5,
                    },
                    "max_skills": {
                        "type": "integer",
                        "description": "Maximum number of skill documents to return (default 3).",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
            parallel_safe=True,
            read_only=True,
        )
        self._memory = memory_manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query: str = arguments.get("query", "")
        max_episodes: int = int(arguments.get("max_episodes", 5))
        max_skills: int = int(arguments.get("max_skills", 3))

        if not query.strip():
            return ToolResult(output="No query provided.", success=False)

        episodes = await self._memory.search_episodes(query, limit=max_episodes)
        skills = await self._memory.search_skills(query, limit=max_skills)

        if not episodes and not skills:
            return ToolResult(output="No relevant memory found for this query.", success=True)

        parts: list[str] = []

        if episodes:
            parts.append("## Relevant Past Episodes")
            for ep in episodes:
                date_str = ep.created_at[:10] if ep.created_at else "unknown date"
                tag_str = f" [{', '.join(ep.tags)}]" if ep.tags else ""
                parts.append(f"[{date_str}] Session {ep.agent_id}/{ep.session_id}{tag_str}:")
                parts.append(ep.summary)
                parts.append("")

        if skills:
            parts.append("## Relevant Skills")
            for skill in skills:
                parts.append(
                    f"**{skill.name}** (v{skill.version}, used {skill.use_count}x) — {skill.description}"
                )
                # Include skill body so the agent can follow the workflow
                if skill.body:
                    parts.append(skill.body.strip())
                parts.append("")
            # Bump use_count for returned skills (fire-and-forget)
            for skill in skills:
                import asyncio
                asyncio.ensure_future(self._memory.increment_skill_use_count(skill.name))

        return ToolResult(output="\n".join(parts).strip(), success=True)


class SaveSkillTool(BaseTool):
    """Create or update a procedural skill document in the skill library."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        super().__init__(
            name="save_skill",
            description=(
                "Save a reusable workflow as a skill document. "
                "Call this after completing a multi-step task that is worth repeating. "
                "If a skill with the same name exists it will be patched (sections updated, version bumped). "
                "Use the agentskills.io format: include ## Prerequisites, ## Steps, and ## Gotchas sections."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short skill name in lowercase-hyphenated form (e.g. 'docker-compose-deploy').",
                    },
                    "description": {
                        "type": "string",
                        "description": "One-sentence description of what this skill does and when to use it.",
                    },
                    "body": {
                        "type": "string",
                        "description": (
                            "Markdown body of the skill. Should include:\n"
                            "## Prerequisites\n"
                            "## Steps\n"
                            "## Gotchas\n"
                        ),
                    },
                    "compatibility": {
                        "type": "string",
                        "description": "Optional environment requirements (e.g. 'Python 3.11+, Docker 24+').",
                        "default": "",
                    },
                },
                "required": ["name", "description", "body"],
            },
            parallel_safe=False,
            read_only=False,
        )
        self._memory = memory_manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from proxi.memory.schema import SkillDoc

        name: str = arguments.get("name", "").strip()
        description: str = arguments.get("description", "").strip()
        body: str = arguments.get("body", "").strip()
        compatibility: str = arguments.get("compatibility", "").strip()

        if not name:
            return ToolResult(output="'name' is required.", success=False)
        if not description:
            return ToolResult(output="'description' is required.", success=False)
        if not body:
            return ToolResult(output="'body' is required.", success=False)

        doc = SkillDoc(
            name=name,
            description=description,
            body=body,
            compatibility=compatibility,
        )
        await self._memory.save_skill(doc)
        return ToolResult(
            output=f"Skill '{name}' saved to memory library.",
            success=True,
        )


class UpdateUserModelTool(BaseTool):
    """Update the persistent user profile (USER.md) with new observations."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        super().__init__(
            name="update_user_model",
            description=(
                "Update the persistent user profile with new observations about the user's "
                "preferences, communication style, environment, or coding conventions. "
                "Provide one or more ## sections to replace. Sections not included are preserved. "
                "Available sections: ## Preferences, ## Communication Style, ## Environment, ## Coding Conventions."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": (
                            "Markdown with ## section headers. Each section replaces the corresponding "
                            "section in USER.md. Example:\n"
                            "## Preferences\n- Prefers TypeScript over JavaScript\n"
                            "## Coding Conventions\n- Uses 2-space indent in TypeScript"
                        ),
                    },
                },
                "required": ["patch"],
            },
            parallel_safe=False,
            read_only=False,
        )
        self._memory = memory_manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        patch: str = arguments.get("patch", "").strip()
        if not patch:
            return ToolResult(output="'patch' is required.", success=False)
        await self._memory.update_user_model(patch)
        return ToolResult(output="User model updated.", success=True)
