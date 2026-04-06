"""Tests for proxi.memory.manager and proxi.memory.schema."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from proxi.memory.manager import MemoryManager, _merge_sections, _bump_patch_version, _split_sections
from proxi.memory.schema import EpisodeSummary, SkillDoc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    return tmp_path / "memory"


@pytest.fixture
def manager(memory_dir: Path) -> MemoryManager:
    mgr = MemoryManager(memory_dir=memory_dir)
    mgr.init()
    return mgr


# ---------------------------------------------------------------------------
# Episodic memory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_search_episode(manager: MemoryManager) -> None:
    episode = EpisodeSummary(
        agent_id="proxi",
        session_id="test-session-1",
        summary="Fixed a database timeout by increasing the connection pool size.",
        full_text="USER: Fix the timeout error. TOOL RESULT: Pool size updated to 20.",
        tags=["database", "timeout", "config"],
    )
    await manager.save_episode(episode)

    results = await manager.search_episodes("database timeout")
    assert len(results) == 1
    assert results[0].agent_id == "proxi"
    assert results[0].session_id == "test-session-1"
    assert "database" in results[0].tags


@pytest.mark.asyncio
async def test_search_episode_no_match(manager: MemoryManager) -> None:
    episode = EpisodeSummary(
        agent_id="proxi",
        session_id="test-session-2",
        summary="Set up docker-compose for a Node.js project.",
        full_text="USER: Set up docker compose. ASSISTANT: Done.",
        tags=["docker", "nodejs"],
    )
    await manager.save_episode(episode)

    results = await manager.search_episodes("kubernetes networking")
    assert results == []


@pytest.mark.asyncio
async def test_search_episode_respects_limit(manager: MemoryManager) -> None:
    for i in range(5):
        await manager.save_episode(EpisodeSummary(
            agent_id="proxi",
            session_id=f"session-{i}",
            summary=f"Worked on python project {i}.",
            full_text=f"USER: Help with python {i}.",
            tags=["python"],
        ))

    results = await manager.search_episodes("python", limit=3)
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# Skill (procedural) memory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_search_skill(manager: MemoryManager) -> None:
    doc = SkillDoc(
        name="docker-compose-deploy",
        description="Deploy multi-service apps with docker-compose. Use when deploying containerized services.",
        body="## Prerequisites\n- Docker 20+\n\n## Steps\n1. Run docker-compose up\n\n## Gotchas\n- Use --build flag",
        compatibility="Docker 20+, docker-compose v2",
    )
    await manager.save_skill(doc)

    results = await manager.search_skills("docker deploy")
    assert len(results) == 1
    assert results[0].name == "docker-compose-deploy"
    assert "docker" in results[0].description.lower()


@pytest.mark.asyncio
async def test_skill_name_sanitized(manager: MemoryManager) -> None:
    doc = SkillDoc(
        name="My Skill With Spaces",
        description="Test skill.",
        body="## Steps\n1. Do stuff",
    )
    await manager.save_skill(doc)

    results = await manager.search_skills("test skill")
    assert len(results) == 1
    assert results[0].name == "my-skill-with-spaces"


@pytest.mark.asyncio
async def test_save_skill_patches_existing(manager: MemoryManager) -> None:
    original = SkillDoc(
        name="my-workflow",
        description="Original description.",
        body="## Steps\n1. Old step\n\n## Gotchas\n- Watch out",
        version="1.0.0",
    )
    await manager.save_skill(original)

    updated = SkillDoc(
        name="my-workflow",
        description="Updated description.",
        body="## Steps\n1. New step — improved",
    )
    await manager.save_skill(updated)

    results = await manager.search_skills("my-workflow")
    assert len(results) == 1
    skill = results[0]
    assert skill.description == "Updated description."
    # Version should have been bumped
    assert skill.version != "1.0.0"
    # Gotchas section should be preserved from original
    assert "Gotchas" in skill.body or "gotchas" in skill.body.lower()
    # Steps should reflect the update
    assert "New step" in skill.body


@pytest.mark.asyncio
async def test_increment_use_count(manager: MemoryManager) -> None:
    doc = SkillDoc(
        name="counter-skill",
        description="A skill for counting.",
        body="## Steps\n1. Count",
        use_count=0,
    )
    await manager.save_skill(doc)
    await manager.increment_skill_use_count("counter-skill")

    results = await manager.search_skills("counter")
    assert results[0].use_count == 1


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

def test_get_user_model_empty(manager: MemoryManager) -> None:
    content = manager.get_user_model()
    # Should return the template (headers only, no content)
    assert "## Preferences" in content or content == ""


@pytest.mark.asyncio
async def test_update_user_model_replaces_section(manager: MemoryManager) -> None:
    patch = "## Preferences\n- Prefers TypeScript over JavaScript\n- Uses 2-space indent"
    await manager.update_user_model(patch)

    content = manager.get_user_model()
    assert "TypeScript" in content
    assert "2-space indent" in content


@pytest.mark.asyncio
async def test_update_user_model_preserves_other_sections(manager: MemoryManager) -> None:
    # Set up initial user model
    await manager.update_user_model(
        "## Communication Style\n- Prefers concise answers\n"
        "## Environment\n- macOS + zsh"
    )
    # Update only preferences
    await manager.update_user_model("## Preferences\n- Uses Python 3.12")

    content = manager.get_user_model()
    assert "Python 3.12" in content
    assert "concise answers" in content
    assert "macOS" in content


@pytest.mark.asyncio
async def test_update_user_model_appends_new_section(manager: MemoryManager) -> None:
    await manager.update_user_model("## Custom Section\n- Something new")
    content = manager.get_user_model()
    assert "Custom Section" in content
    assert "Something new" in content


# ---------------------------------------------------------------------------
# Enable / disable
# ---------------------------------------------------------------------------

def test_memory_enabled_default_no_config(memory_dir: Path) -> None:
    mgr = MemoryManager(memory_dir=memory_dir, gateway_config_path=None)
    assert mgr.is_enabled("any-agent") is True


def test_memory_enabled_from_gateway_yml(tmp_path: Path) -> None:
    gateway_yml = tmp_path / "gateway.yml"
    gateway_yml.write_text(
        "agents:\n"
        "  proxi:\n"
        "    soul: agents/proxi/Soul.md\n"
        "    memory:\n"
        "      enabled: false\n"
        "  other:\n"
        "    soul: agents/other/Soul.md\n",
        encoding="utf-8",
    )
    mgr = MemoryManager(memory_dir=tmp_path / "memory", gateway_config_path=gateway_yml)
    assert mgr.is_enabled("proxi") is False
    assert mgr.is_enabled("other") is True   # default True
    assert mgr.is_enabled("unknown") is True  # default True


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def test_split_and_merge_sections() -> None:
    base = "## A\nfoo\n\n## B\nbar"
    patch = "## A\nupdated foo"
    merged = _merge_sections(base, patch)
    assert "updated foo" in merged
    assert "bar" in merged  # B preserved


def test_merge_sections_adds_new() -> None:
    base = "## A\nfoo"
    patch = "## Z\nzap"
    merged = _merge_sections(base, patch)
    assert "foo" in merged
    assert "zap" in merged


def test_bump_patch_version() -> None:
    assert _bump_patch_version("1.0.0") == "1.0.1"
    assert _bump_patch_version("2.3.9") == "2.3.10"
    assert _bump_patch_version("1.0") == "1.1"
    assert _bump_patch_version("bad") == "bad"


def test_skill_doc_roundtrip() -> None:
    doc = SkillDoc(
        name="test-skill",
        description="A test skill.",
        body="## Steps\n1. Do the thing",
        compatibility="Python 3.11+",
        version="1.2.3",
        created_by="proxi",
        created_at="2026-04-04",
        use_count=5,
    )
    rendered = doc.to_skill_md()
    parsed = SkillDoc.from_skill_md("test-skill", rendered)

    assert parsed.name == "test-skill"
    assert parsed.description == "A test skill."
    assert "Do the thing" in parsed.body
    assert parsed.compatibility == "Python 3.11+"
    assert parsed.version == "1.2.3"
    assert parsed.created_by == "proxi"
    assert parsed.use_count == 5
