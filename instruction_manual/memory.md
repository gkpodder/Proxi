# Memory System

Proxi's memory system gives agents three forms of persistence across sessions: a record of past conversations (episodic), a library of reusable procedures (procedural/skills), and a profile of the user's preferences (user model). All three are managed by a single `MemoryManager` instance, initialized at gateway startup and shared across all agent lanes.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Storage Layout](#storage-layout)
- [Memory Types](#memory-types)
  - [Episodic Memory](#episodic-memory)
  - [Skill Library (Procedural Memory)](#skill-library-procedural-memory)
  - [User Model](#user-model)
- [Agent Tools](#agent-tools)
- [Session Summarization Pipeline](#session-summarization-pipeline)
- [How Proxi Learns Over Time](#how-proxi-learns-over-time)
- [Configuration](#configuration)
- [Enabling and Disabling Per Agent](#enabling-and-disabling-per-agent)

---

## Overview

```
Session ends
    └─► _summarize_session()           ← background task, fire-and-forget
            └─► LLM (cheap model)      ← generates ~200-word summary + tags
                    └─► MemoryManager.save_episode()
                            └─► SQLite FTS5 (memory.db)

Agent turn starts
    └─► search_memory tool             ← agent calls this when context is relevant
            ├─► search_episodes()      ← FTS5 full-text search over past sessions
            └─► search_skills()        ← keyword search over SKILL.md files

Agent observes something worth saving
    ├─► save_skill tool                ← stores a reusable workflow
    └─► update_user_model tool         ← updates USER.md sections
```

---

## Architecture

```
proxi/memory/
├── __init__.py          # re-exports MemoryManager, EpisodeSummary, SkillDoc
├── manager.py           # MemoryManager — central interface, async wrappers
├── schema.py            # SQLite schema + init_db(), EpisodeSummary, SkillDoc dataclasses
└── summarizer.py        # Summarizer — in-context window trimmer (separate concern)

proxi/tools/
└── memory_tools.py      # SearchMemoryTool, SaveSkillTool, UpdateUserModelTool

proxi/gateway/lanes/
└── lane.py              # _summarize_session(), _build_summarizer_client()
```

`MemoryManager` is instantiated once in `server.py` lifespan and passed into each `AgentLane`. All SQLite I/O runs in a thread-pool executor via `asyncio.run_in_executor` so it never blocks the event loop.

---

## Storage Layout

All memory lives under `~/.proxi/memory/` (inside the workspace root):

```
~/.proxi/memory/
├── memory.db            ← SQLite database (episodic memory)
├── USER.md              ← user profile (preferences, style, environment, conventions)
└── skills/
    └── <skill-name>/
        └── SKILL.md     ← procedural skill document
```

---

## Memory Types

### Episodic Memory

Stores a summary of each past session so the agent can recall what happened in previous conversations.

**Storage:** SQLite table `episodes` with an FTS5 virtual table (`episodes_fts`) for full-text search. Three SQL triggers keep the FTS index in sync with the base table automatically on INSERT, UPDATE, and DELETE.

**Schema:**

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment row ID |
| `agent_id` | TEXT | Which agent the session belonged to |
| `session_id` | TEXT | Session identifier |
| `summary` | TEXT | LLM-generated ~200-word summary |
| `full_text` | TEXT | Raw transcript (user/assistant turns + tool results) used for FTS matching |
| `tags` | TEXT | JSON array of 3–5 topic tags (e.g. `["docker","deployment"]`) |
| `created_at` | TEXT | ISO-8601 timestamp |

**When it's written:** automatically at the end of each session with at least 3 user turns (see [Session Summarization Pipeline](#session-summarization-pipeline)).

**How to search:** the `search_memory` tool runs an FTS5 `MATCH` query ranked by relevance. Special FTS5 operators (`"`, `*`, `^`) are stripped from user queries to prevent syntax errors.

---

### Skill Library (Procedural Memory)

Stores reusable multi-step workflows as structured Markdown files. The agent writes a skill after completing a task worth repeating; it reads skills back when it recognizes a similar task.

**Storage:** one directory per skill under `~/.proxi/memory/skills/<skill-name>/SKILL.md`. Files follow the [agentskills.io](https://agentskills.io) format.

**SKILL.md format:**

```markdown
---
name: docker-compose-deploy
description: Deploy a service using Docker Compose with zero-downtime rolling restart.
compatibility: Docker 24+, Compose v2
metadata:
  version: "1.0.2"
  created_by: "proxi"
  created_at: "2025-11-03"
  use_count: 4
---

## Prerequisites
- Docker and Compose v2 installed
- `.env` file with image tag set

## Steps
1. Pull the new image: `docker compose pull <service>`
2. Rolling restart: `docker compose up -d --no-deps <service>`
3. Verify: `docker compose ps`

## Gotchas
- `--no-deps` prevents restarting dependent services unintentionally.
- Check health checks are passing before considering the deploy done.
```

**Skill lifecycle:**

```
save_skill called
    ├─► skill does not exist → write new SKILL.md (version 1.0.0)
    └─► skill exists → patch: merge ## sections, bump patch version (1.0.2 → 1.0.3)
                            preserve: name, created_by, created_at, use_count

search_memory or search_skills called
    └─► term-frequency scoring across name + description + body
            └─► top-k results returned, use_count incremented (fire-and-forget)
```

**Patching behavior:** when `save_skill` is called for a skill that already exists, only the `##` sections present in the new body are replaced. Sections not included in the update are preserved. The version patch component is bumped automatically (e.g. `1.0.2 → 1.0.3`).

**Use count:** every time a skill is returned by `search_memory` or `search_skills`, its `use_count` is incremented asynchronously. This provides a lightweight signal of which skills are most frequently useful.

---

### User Model

A persistent Markdown file (`USER.md`) representing the agent's understanding of the user. Updated incrementally as the agent observes new information.

**Storage:** `~/.proxi/memory/USER.md`, capped at 2400 characters (~600 tokens).

**Default sections:**

```markdown
## Preferences

## Communication Style

## Environment

## Coding Conventions
```

**Update behavior:** the `update_user_model` tool accepts a patch containing one or more `##` sections. Sections present in the patch replace the matching section in `USER.md`; sections not mentioned are left untouched. New sections in the patch that don't exist yet are appended.

**Size cap:** if the updated file would exceed 2400 characters it is truncated. Keep individual section content concise.

---

## Agent Tools

Three tools are registered in the live tool tier (always in context) when memory is enabled for an agent:

| Tool | When the agent uses it |
|---|---|
| `search_memory` | When the user references a past task, a recurring workflow, or the agent wants to check if a how-to procedure already exists. Searches both episodes and skills in one call. |
| `save_skill` | After completing a multi-step task worth repeating. Accepts `name`, `description`, `body` (with `## Prerequisites`, `## Steps`, `## Gotchas`), and optional `compatibility`. |
| `update_user_model` | When the agent observes new information about the user's preferences, environment, style, or conventions. Provide only the sections that changed. |

All three tools are registered per-lane in `server.py` and receive the shared `MemoryManager` instance.

---

## Session Summarization Pipeline

At the end of every session (when an `AgentLane` finishes processing), a background task summarizes the conversation and stores it as an episode.

**Trigger condition:** at least 3 user turns in the session history. Sessions shorter than this are skipped to avoid storing low-signal noise.

**Pipeline:**

```
AgentLane finishes
    └─► asyncio.ensure_future(_summarize_session(...))   ← fire-and-forget
            ├─► build compact transcript
            │     - user/assistant turns: up to 500 chars each
            │     - tool results: up to 200 chars each
            │     - total capped at 6000 chars
            ├─► _build_summarizer_client(llm_client)
            │     1. PROXI_MEMORY_SUMMARIZER_MODEL env var (explicit override)
            │     2. Cheap model for detected provider:
            │           anthropic → claude-haiku-4-5-20251001
            │           openai    → gpt-4o-mini
            │     3. Fallback: reuse the main llm_client as-is
            │           (covers vllm / unknown providers, or key-fetch failures)
            └─► llm_client.generate(summary prompt)
                    └─► parse summary + TAGS: [...] from last line
                            └─► MemoryManager.save_episode()
```

**Summarizer prompt output format:**

The LLM is instructed to produce a ~200-word summary ending with a `TAGS:` line:

```
... summary text ...
TAGS: ["docker", "deployment", "debugging"]
```

The tags are parsed from that final line and stored separately in the `tags` column for more targeted retrieval.

---

## How Proxi Learns Over Time

Proxi does not retrain or fine-tune the underlying LLM. Instead, learning happens through the memory system: each interaction leaves behind structured artifacts that are injected into future context, making the agent progressively more accurate and efficient for a given user and set of tasks.

### What changes after each session

| What happened | What gets stored | Effect on future sessions |
|---|---|---|
| A meaningful conversation (3+ user turns) | Episode summary + tags in `memory.db` | Agent can recall what was done, decisions made, and errors resolved |
| A multi-step task the agent completed successfully | `SKILL.md` in `skills/` | Agent can follow the same procedure next time without rediscovering each step |
| The user expressed a preference or showed a working style | Updated section in `USER.md` | Agent adapts tone, format, tooling choices, and code style to match the user |

### The learning loop

```
User asks for something
    └─► Agent searches memory (search_memory)
            ├─► Relevant episodes surface  →  "I've done this before, here's what worked"
            └─► Matching skill found       →  "I have a procedure for this, follow it"

Agent completes a task
    ├─► Was this a multi-step workflow?
    │       └─► Yes → save_skill          →  skill library grows
    ├─► Did I learn something about the user?
    │       └─► Yes → update_user_model   →  user profile updated
    └─► Session ends
            └─► Summarize → save episode  →  episodic memory grows
```

### How each memory type contributes to improvement

**Episodic memory** prevents the agent from starting from scratch every session. If you've asked Proxi to set up a project before, it knows the decisions that were made, what failed and why, and what the final outcome was. This is especially useful for long-running projects where context would otherwise be lost between conversations.

**Skills** make the agent more reliable at repeated tasks. The first time Proxi deploys your Docker service, it may make mistakes or take extra steps. Once that workflow is saved as a skill, future runs follow the proven procedure — including the gotchas that were learned the hard way. Skills also improve incrementally: each call to `save_skill` for an existing skill patches only the changed sections and bumps the version, so the skill document gets more accurate over time without losing earlier knowledge.

**User model** makes the agent feel less generic. After a few sessions, Proxi knows you prefer TypeScript over JavaScript, that your project uses 2-space indentation, that you want concise answers, and that your machine runs macOS with `brew`. It stops asking questions you've already answered and stops making suggestions that conflict with your known preferences.

### What does not change

- The base LLM is not modified. Memory affects what context the model receives, not the model's weights.
- Memory is scoped per agent. Different agents (`proxi`, `work`, `personal`) maintain separate episode databases, skill libraries, and user models. An agent only learns from its own sessions.
- Skills and episodes are never automatically deleted. The library grows as long as the agent is used. You can inspect and edit files directly under `~/.proxi/memory/` if you want to remove or correct something.

### Compounding effect over time

The three memory types compound. A mature Proxi instance for a developer might look like:

- 50+ episodic summaries covering past debugging sessions, deployments, and refactors
- 10–20 skills covering common project workflows with version histories
- A user model that captures preferred languages, tools, verbosity level, and coding conventions

At that point, when the user asks "set up the staging deploy like last time," the agent can search episodes for the previous deploy, load the relevant skill for the deployment procedure, and format the output according to the user's known preferences — all without the user needing to explain anything.

---

## Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `PROXI_MEMORY_SUMMARIZER_MODEL` | *(provider default)* | Override the model used for session summarization. If unset, the cheapest model for the active provider is selected automatically. |

### Workspace root

Memory files live at `<PROXI_HOME>/memory/` where `PROXI_HOME` defaults to `~/.proxi`. Override `PROXI_HOME` to point multiple Proxi instances at different memory stores.

---

## Enabling and Disabling Per Agent

Memory is enabled by default for all agents. To disable it for a specific agent, add the following to `~/.proxi/gateway.yml`:

```yaml
agents:
  my-agent:
    memory:
      enabled: false
```

When disabled, the `search_memory`, `save_skill`, and `update_user_model` tools are not registered for that agent's lanes, and no episodic summarization runs at session end.
