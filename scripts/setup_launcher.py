"""Project setup helper for Node surfaces and API key database initialization."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from proxi.security.key_store import init_db


def _resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _find_package_manager() -> str:
    """Use bun for dependency installation across all Node surfaces."""
    resolved = shutil.which("bun")
    if resolved:
        return resolved
    raise RuntimeError("bun was not found on PATH")


def _install_node_dependencies(project_root: Path, package_manager: str, folder: str) -> None:
    target = project_root / folder
    if not target.is_dir():
        raise RuntimeError(f"Missing directory: {target}")

    print(f"Installing Node dependencies in {folder} using {package_manager}...")
    result = subprocess.run(
        [package_manager, "install"],
        cwd=str(target),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Dependency install failed in {folder} (exit code {result.returncode})")


def _initialize_api_keys_db(project_root: Path) -> None:
    db_path = project_root / "config" / "api_keys.db"
    existed = db_path.exists()
    initialized = init_db(db_path=db_path)
    if existed:
        print(f"API key store already present and verified at {initialized}")
    else:
        print(f"Created API key store at {initialized}")


def main() -> None:
    project_root = _resolve_project_root()

    try:
        package_manager = _find_package_manager()
    except RuntimeError as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        sys.exit(1)

    targets = ("cli_ink", "react_frontend", "discord_relay")
    for folder in targets:
        try:
            _install_node_dependencies(project_root, package_manager, folder)
        except RuntimeError as exc:
            print(f"Setup failed: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        _initialize_api_keys_db(project_root)
    except Exception as exc:
        print(f"Setup failed during DB initialization: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Setup complete. You can now run TUI, frontend, and Discord relay.")
