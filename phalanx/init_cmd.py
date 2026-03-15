"""phalanx init — IDE detection and skill file deployment (global + workspace)."""

from __future__ import annotations

import shutil
import sys
import os
from pathlib import Path


def load_skill(backend: str) -> str:
    """Load the universal skill body for the given backend."""
    # We use the same skill body for all backends now.
    skill_path = Path(__file__).parent / "soul" / "skill_body.md"
    return skill_path.read_text(encoding="utf-8")


def _print(msg: str) -> None:
    """Print and flush immediately — critical before os.execvp replaces the process."""
    print(msg, flush=True)


HOME = Path.home()

# Global skill paths per CLI — each is a dedicated phalanx-owned file.
# Cursor: skills-cursor/<name>/SKILL.md (Cursor's convention, "skills-cursor" is fixed)
# Claude: commands/<name>.md (Claude uses flat .md files as slash commands)
# Gemini: skills/<name>/SKILL.md (Gemini's native skill format)
# Codex:  skills/<name>/SKILL.md (Codex's native skill format)
_GLOBAL_SKILL_PATHS: dict[str, Path] = {
    "cursor": HOME / ".cursor" / "skills" / "phalanx" / "SKILL.md",
    "claude": HOME / ".claude" / "commands" / "phalanx.md",
    "gemini": HOME / ".gemini" / "skills" / "phalanx" / "SKILL.md",
    "codex": HOME / ".codex" / "skills" / "phalanx" / "SKILL.md",
}


def detect_available_backends() -> list[str]:
    """Detect which agent CLIs are installed."""
    backends = []
    if shutil.which("agent"):
        backends.append("cursor")
    if shutil.which("claude"):
        backends.append("claude")
    if shutil.which("gemini"):
        backends.append("gemini")
    if shutil.which("codex"):
        backends.append("codex")
    return backends


def _skill_is_current(path: Path, backend: str) -> bool:
    """Check if the skill file exists and matches the current version."""
    if not path.exists():
        return False
    return path.read_text().strip() == load_skill(backend).strip()


def install_global_skill(backend: str) -> Path:
    """Install the phalanx skill to the global location for a backend."""
    import subprocess

    path = _GLOBAL_SKILL_PATHS[backend]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(load_skill(backend))

    if backend == "gemini" and shutil.which("gemini"):
        subprocess.run(
            ["gemini", "skills", "enable", "phalanx-orchestration"],
            capture_output=True,
            timeout=15,
        )

    return path


def _is_workspace(directory: Path) -> bool:
    """Detect if a directory looks like a project workspace."""
    return (directory / ".git").exists() or (directory / ".cursor").exists()


def _cursor_rule_path(workspace: Path) -> Path:
    return workspace / ".cursor" / "rules" / "phalanx.mdc"


def _cursor_rule_is_current(workspace: Path) -> bool:
    path = _cursor_rule_path(workspace)
    if not path.exists():
        return False
    return path.read_text().strip() == load_skill("cursor").strip()


def _ensure_cursor_workspace_rule(workspace: Path) -> None:
    """For cursor backend: ensure .cursor/rules/phalanx.mdc exists in the workspace.

    Workaround for Cursor CLI TUI mode not loading skills (agentSkill toolType bug).
    Rules with alwaysApply: true ARE loaded in TUI mode.
    """
    if _cursor_rule_is_current(workspace):
        return

    path = _cursor_rule_path(workspace)

    if path.exists():
        path.write_text(load_skill("cursor"))
        _print(f"Phalanx workspace rule updated: {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(load_skill("cursor"))
    _print(f"Phalanx workspace rule added: {path}")


# ── Workspace init (phalanx init) ──────────────────────────


def check_and_prompt_skill(backend: str, workspace: Path | None = None) -> None:
    """Check if phalanx skill is installed globally for the backend.

    - Missing: prompt user for first-time install
    - Outdated: auto-update silently
    - Current: no action

    For cursor backend, also handles workspace-level rule deployment
    (workaround for TUI mode skill loading bug).

    Called at startup of `phalanx run`.
    """
    if backend not in _GLOBAL_SKILL_PATHS:
        return

    # ── Global skill ──
    path = _GLOBAL_SKILL_PATHS[backend]

    if _skill_is_current(path, backend):
        pass
    elif path.exists():
        installed_path = install_global_skill(backend)
        _print(f"Phalanx skill updated: {installed_path}")
    else:
        prompt_msg = (
            f"Phalanx skill not found for {backend}.\n"
            f"Install to {path} so the agent knows about phalanx? [Y/n] "
        )
        sys.stdout.flush()
        response = input(prompt_msg).strip().lower()
        if response in ("", "y", "yes"):
            installed_path = install_global_skill(backend)
            _print(f"Phalanx skill installed: {installed_path}")
        else:
            _print("Skipped. The agent won't know about phalanx team commands.")

    # ── Cursor workspace rule (TUI workaround) ──
    if backend == "cursor":
        ws = workspace or Path.cwd()
        if _is_workspace(ws):
            _ensure_cursor_workspace_rule(ws)
        else:
            _print(
                "Note: No workspace detected (no .git or .cursor directory).\n"
                "Phalanx skill may not load in Cursor interactive mode.\n"
                "Run phalanx from a project directory for full integration."
            )


# ── Workspace init (phalanx init) ──────────────────────────


def write_cursor_skill(workspace: Path) -> Path:
    skill_dir = workspace / ".cursor" / "rules"
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "phalanx.mdc"
    path.write_text(load_skill("cursor"))
    return path


def write_claude_skill(workspace: Path) -> Path:
    skill_dir = workspace / ".claude" / "commands"
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "phalanx.md"
    path.write_text(load_skill("claude"))
    return path


def write_gemini_skill(workspace: Path) -> Path:
    skill_dir = workspace / ".gemini"
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "phalanx-policy.md"
    path.write_text(load_skill("gemini"))
    return path


def write_codex_skill(workspace: Path) -> Path | None:
    """Optionally write AGENTS.md for Codex.

    Disabled by default to avoid modifying repository roots unexpectedly.
    Enable explicitly with PHALANX_WRITE_CODEX_AGENTS=1.
    """
    if os.environ.get("PHALANX_WRITE_CODEX_AGENTS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return None

    path = workspace / "AGENTS.md"
    content = load_skill("codex")
    if path.exists():
        existing = path.read_text()
        if "phalanx" not in existing.lower():
            path.write_text(existing + "\n\n" + content)
    else:
        path.write_text(content)
    return path


_SKILL_WRITERS = {
    "cursor": write_cursor_skill,
    "claude": write_claude_skill,
    "gemini": write_gemini_skill,
    "codex": write_codex_skill,
}


def init_workspace(workspace: Path) -> dict[str, list[str]]:
    """Initialize workspace metadata.

    Global skill installation is handled lazily by `check_and_prompt_skill()`
    when a backend is actually used. We intentionally avoid creating
    workspace-level provider files here, except Cursor's rule workaround which
    is also applied lazily only when Cursor is selected.
    """
    ides = detect_available_backends()
    created: list[str] = []

    phalanx_dir = workspace / ".phalanx"
    phalanx_dir.mkdir(exist_ok=True)

    return {"ides_detected": ides, "skills_created": created}
