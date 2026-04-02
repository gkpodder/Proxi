"""Tests for coding agent tools: PathGuard, GrepTool, GlobTool, EditFileTool,
ReadFileTool (offset/limit), ApplyPatchTool."""

from pathlib import Path

import pytest

from proxi.tools.path_guard import PathGuard, PathGuardError
from proxi.tools.grep import GrepTool
from proxi.tools.glob_tool import GlobTool
from proxi.tools.filesystem import EditFileTool, ReadFileTool
from proxi.tools.diff import ApplyPatchTool
from proxi.tools.shell import ExecuteCodeTool
from proxi.tools.coding import build_coding_tools, register_coding_tools
from proxi.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# PathGuard
# ---------------------------------------------------------------------------


def test_path_guard_allows_within_base(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    allowed = tmp_path / "sub" / "file.txt"
    allowed.parent.mkdir()
    allowed.touch()
    result = guard.validate(allowed)
    assert result == allowed.resolve()


def test_path_guard_rejects_outside_base(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    with pytest.raises(PathGuardError):
        guard.validate(outside)


def test_path_guard_rejects_dotdot(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    escape = tmp_path / ".." / "escape"
    with pytest.raises(PathGuardError):
        guard.validate(escape)


def test_path_guard_no_base_allows_anything(tmp_path: Path) -> None:
    guard = PathGuard(None)
    result = guard.validate(tmp_path / "anything")
    assert result is not None


def test_path_guard_result_returns_error_tool_result(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    resolved, err = guard.guard_result(outside)
    assert resolved is None
    assert err is not None
    assert not err.success
    assert "outside" in err.error.lower() or "working directory" in err.error.lower()


def test_path_guard_symlink_traversal(tmp_path: Path) -> None:
    """Symlink pointing outside base_dir should be rejected."""
    inside = tmp_path / "link"
    target = tmp_path.parent / "target"
    target.mkdir(exist_ok=True)
    inside.symlink_to(target)

    guard = PathGuard(tmp_path)
    with pytest.raises(PathGuardError):
        guard.validate(inside)


# ---------------------------------------------------------------------------
# GrepTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_finds_pattern(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text("def hello():\n    pass\n# TODO: improve\n")
    tool = GrepTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "TODO"})
    assert result.success
    assert "TODO" in result.output


@pytest.mark.asyncio
async def test_grep_no_matches(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("x = 1\n")
    tool = GrepTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "XYZXYZXYZ_NOMATCH"})
    assert result.success
    assert "no matches" in result.output


@pytest.mark.asyncio
async def test_grep_rejects_path_outside_cwd(tmp_path: Path) -> None:
    outside = tmp_path.parent
    tool = GrepTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "foo", "path": str(outside)})
    assert not result.success
    assert "outside" in result.error.lower() or "working directory" in result.error.lower()


@pytest.mark.asyncio
async def test_grep_glob_filter(tmp_path: Path) -> None:
    (tmp_path / "file.py").write_text("# match\n")
    (tmp_path / "file.txt").write_text("# match\n")
    tool = GrepTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "match", "glob": "*.py"})
    assert result.success
    assert "file.py" in result.output
    assert "file.txt" not in result.output


@pytest.mark.asyncio
async def test_grep_files_output_mode(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("needle\n")
    (tmp_path / "b.py").write_text("nothing\n")
    tool = GrepTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "needle", "output_mode": "files"})
    assert result.success
    assert "a.py" in result.output
    assert "b.py" not in result.output


@pytest.mark.asyncio
async def test_grep_truncates_output(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("\n".join(f"line {i}" for i in range(300)))
    tool = GrepTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "line", "max_results": 10})
    assert result.success
    assert "truncated" in result.output


# ---------------------------------------------------------------------------
# GlobTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_glob_matches_pattern(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("")
    (tmp_path / "src" / "util.py").write_text("")
    (tmp_path / "README.md").write_text("")
    tool = GlobTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "**/*.py"})
    assert result.success
    assert "main.py" in result.output
    assert "util.py" in result.output
    assert "README.md" not in result.output


@pytest.mark.asyncio
async def test_glob_no_matches(tmp_path: Path) -> None:
    tool = GlobTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "*.xyz"})
    assert result.success
    assert "no matches" in result.output


@pytest.mark.asyncio
async def test_glob_rejects_path_outside_cwd(tmp_path: Path) -> None:
    outside = tmp_path.parent
    tool = GlobTool(PathGuard(tmp_path))
    result = await tool.execute({"pattern": "**/*.py", "path": str(outside)})
    assert not result.success


# ---------------------------------------------------------------------------
# EditFileTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_file_replaces_unique_string(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    tool = EditFileTool(PathGuard(tmp_path))
    result = await tool.execute({
        "file_path": str(f),
        "old_string": "return 1",
        "new_string": "return 2",
    })
    assert result.success
    assert f.read_text() == "def foo():\n    return 2\n"


@pytest.mark.asyncio
async def test_edit_file_errors_on_not_found(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("x = 1\n")
    tool = EditFileTool(PathGuard(tmp_path))
    result = await tool.execute({
        "file_path": str(f),
        "old_string": "XYZXYZ",
        "new_string": "abc",
    })
    assert not result.success
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_edit_file_errors_on_ambiguous_match(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("x = 1\nx = 1\n")
    tool = EditFileTool(PathGuard(tmp_path))
    result = await tool.execute({
        "file_path": str(f),
        "old_string": "x = 1",
        "new_string": "x = 2",
    })
    assert not result.success
    assert "2" in result.error  # mentions the count


@pytest.mark.asyncio
async def test_edit_file_replace_all(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("x = 1\nx = 1\n")
    tool = EditFileTool(PathGuard(tmp_path))
    result = await tool.execute({
        "file_path": str(f),
        "old_string": "x = 1",
        "new_string": "x = 9",
        "replace_all": True,
    })
    assert result.success
    assert f.read_text() == "x = 9\nx = 9\n"


@pytest.mark.asyncio
async def test_edit_file_rejects_path_outside_cwd(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("x = 1\n")
    tool = EditFileTool(PathGuard(tmp_path))
    result = await tool.execute({
        "file_path": str(outside),
        "old_string": "x = 1",
        "new_string": "x = 2",
    })
    assert not result.success


# ---------------------------------------------------------------------------
# ReadFileTool — offset/limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_full(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("line1\nline2\nline3\n")
    tool = ReadFileTool()
    result = await tool.execute({"path": str(f)})
    assert result.success
    assert result.output == "line1\nline2\nline3\n"


@pytest.mark.asyncio
async def test_read_file_with_offset_and_limit(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)))
    tool = ReadFileTool()
    result = await tool.execute({"path": str(f), "offset": 3, "limit": 3})
    assert result.success
    lines = result.output.splitlines()
    assert len(lines) == 3
    # Line numbers should appear (cat -n style)
    assert lines[0].startswith("3\t")
    assert "line3" in lines[0]
    assert lines[2].startswith("5\t")


@pytest.mark.asyncio
async def test_read_file_offset_only(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("a\nb\nc\n")
    tool = ReadFileTool()
    result = await tool.execute({"path": str(f), "offset": 2})
    assert result.success
    assert "b" in result.output
    assert "c" in result.output
    # Line 1 should not appear
    assert result.output.count("1\t") == 0


@pytest.mark.asyncio
async def test_read_file_not_found(tmp_path: Path) -> None:
    tool = ReadFileTool()
    result = await tool.execute({"path": str(tmp_path / "missing.txt")})
    assert not result.success


# ---------------------------------------------------------------------------
# ApplyPatchTool (requires git)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_patch_applies_changes(tmp_path: Path) -> None:
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True, capture_output=True)
    f = tmp_path / "hello.py"
    f.write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True)

    patch = (
        "--- a/hello.py\n"
        "+++ b/hello.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 42\n"
    )
    tool = ApplyPatchTool(tmp_path)
    result = await tool.execute({"patch": patch})
    assert result.success
    assert f.read_text() == "x = 42\n"


@pytest.mark.asyncio
async def test_apply_patch_check_only(tmp_path: Path) -> None:
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True, capture_output=True)
    f = tmp_path / "hello.py"
    f.write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True)

    patch = (
        "--- a/hello.py\n"
        "+++ b/hello.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 42\n"
    )
    tool = ApplyPatchTool(tmp_path)
    result = await tool.execute({"patch": patch, "check_only": True})
    assert result.success
    # File should be unchanged since check_only=True
    assert f.read_text() == "x = 1\n"
    assert "validated" in result.output


# ---------------------------------------------------------------------------
# ExecuteCodeTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_code_runs_command(tmp_path: Path) -> None:
    tool = ExecuteCodeTool(working_directory=tmp_path)
    result = await tool.execute({"command": "echo hello"})
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_execute_code_captures_failure(tmp_path: Path) -> None:
    tool = ExecuteCodeTool(working_directory=tmp_path)
    result = await tool.execute({"command": "exit 1"})
    assert not result.success
    assert result.metadata.get("return_code") == 1


# ---------------------------------------------------------------------------
# build_coding_tools / register_coding_tools
# ---------------------------------------------------------------------------


def test_build_coding_tools_returns_all_tools(tmp_path: Path) -> None:
    tools = build_coding_tools(tmp_path)
    names = {t.name for t in tools}
    assert "grep" in names
    assert "glob" in names
    assert "edit_file" in names
    
    assert "apply_patch" in names
    assert "execute_code" in names


def test_register_coding_tools_live(tmp_path: Path) -> None:
    from proxi.tools.registry import ToolRegistry
    registry = ToolRegistry()
    register_coding_tools(registry, working_dir=tmp_path, tier="live")
    names = {t.name for t in registry.list_tools()}
    assert "grep" in names


def test_register_coding_tools_deferred(tmp_path: Path) -> None:
    from proxi.tools.registry import ToolRegistry
    registry = ToolRegistry()
    register_coding_tools(registry, working_dir=tmp_path, tier="deferred")
    live_names = {t.name for t in registry.list_tools()}
    assert "grep" not in live_names
    # Deferred tools should be searchable
    results = registry.search_deferred("search file contents")
    assert len(results) > 0


def test_register_coding_tools_disabled(tmp_path: Path) -> None:
    from proxi.tools.registry import ToolRegistry
    registry = ToolRegistry()
    register_coding_tools(registry, working_dir=tmp_path, tier="disabled")
    names = {t.name for t in registry.list_tools()}
    assert "grep" not in names


# ---------------------------------------------------------------------------
# Workspace: config.yaml creation and read_agent_config
# ---------------------------------------------------------------------------

try:
    import yaml as _yaml  # noqa: F401
    _workspace_available = True
except ImportError:
    _workspace_available = False

_skip_workspace = pytest.mark.skipif(
    not _workspace_available, reason="pyyaml not available in this test environment"
)


@_skip_workspace
def test_create_agent_writes_config_yaml(proxi_home_env: Path) -> None:
    from proxi.workspace import WorkspaceManager  # type: ignore[import]
    mgr = WorkspaceManager()
    info = mgr.create_agent(name="Coder", persona="Expert coder")
    config_path = info.path / "config.yaml"
    assert config_path.exists()
    text = config_path.read_text()
    assert "coding" in text


@_skip_workspace
def test_read_agent_config_returns_dict(proxi_home_env: Path) -> None:
    from proxi.workspace import WorkspaceManager  # type: ignore[import]
    mgr = WorkspaceManager()
    info = mgr.create_agent(name="Coder", persona="x")
    config = mgr.read_agent_config(info.agent_id)
    assert isinstance(config, dict)
    assert config.get("tool_sets", {}).get("coding") == "live"


@_skip_workspace
def test_read_agent_config_missing_returns_empty(proxi_home_env: Path) -> None:
    from proxi.workspace import WorkspaceManager  # type: ignore[import]
    mgr = WorkspaceManager()
    config = mgr.read_agent_config("nonexistent-agent")
    assert config == {}


# ---------------------------------------------------------------------------
# WorkspaceConfig.curr_working_dir
# ---------------------------------------------------------------------------


def test_workspace_config_has_curr_working_dir() -> None:
    from proxi.core.state import WorkspaceConfig
    wc = WorkspaceConfig(
        workspace_root="/tmp",
        agent_id="test",
        session_id="s1",
        global_system_prompt_path="/tmp/sp.md",
        soul_path="/tmp/soul.md",
        history_path="/tmp/h.jsonl",
        plan_path="/tmp/plan.md",
        todos_path="/tmp/todos.md",
        curr_working_dir="/home/user/project",
    )
    assert wc.curr_working_dir == "/home/user/project"


def test_workspace_config_curr_working_dir_defaults_none() -> None:
    from proxi.core.state import WorkspaceConfig
    wc = WorkspaceConfig(
        workspace_root="/tmp",
        agent_id="test",
        session_id="s1",
        global_system_prompt_path="/tmp/sp.md",
        soul_path="/tmp/soul.md",
        history_path="/tmp/h.jsonl",
        plan_path="/tmp/plan.md",
        todos_path="/tmp/todos.md",
    )
    assert wc.curr_working_dir is None
