"""Git worktree management for agent isolation."""

from __future__ import annotations

import subprocess
from pathlib import Path

WORKTREE_BASE = Path.home() / ".phalanx" / "worktrees"


def create_worktree(
    repo_path: Path,
    name: str,
    base_ref: str = "HEAD",
) -> Path:
    """Create an isolated git worktree for an agent.

    Returns the worktree path.
    """
    repo_name = repo_path.name
    wt_path = WORKTREE_BASE / repo_name / name
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "worktree", "add", str(wt_path), "--detach", base_ref],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
    )
    return wt_path


def remove_worktree(repo_path: Path, name: str) -> bool:
    """Remove a worktree by name. Returns True if successfully removed."""
    repo_name = repo_path.name
    wt_path = WORKTREE_BASE / repo_name / name

    if not wt_path.exists():
        return False

    subprocess.run(
        ["git", "worktree", "remove", str(wt_path), "--force"],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
    )
    return True


def list_worktrees(repo_path: Path) -> list[dict[str, str]]:
    """List all worktrees for a repo."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    worktrees = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "detached":
            current["detached"] = "true"
    if current:
        worktrees.append(current)
    return worktrees


def cleanup_team_worktrees(repo_path: Path, team_id: str) -> int:
    """Remove all worktrees whose name starts with the team_id. Returns count."""
    repo_name = repo_path.name
    team_dir = WORKTREE_BASE / repo_name
    if not team_dir.exists():
        return 0

    count = 0
    for wt in team_dir.iterdir():
        if wt.is_dir() and wt.name.startswith(team_id):
            try:
                remove_worktree(repo_path, wt.name)
                count += 1
            except subprocess.CalledProcessError:
                pass
    return count
