"""Soul file loading and dynamic variable injection."""

from __future__ import annotations

from pathlib import Path

SOUL_DIR = Path(__file__).parent

# Per-CLI frontmatter — each CLI has different requirements.
# Cursor: supports alwaysApply, description, name
# Claude: uses description as slash-command trigger
# Gemini: strict — only name + description, no extra fields, needs "Use when" wording
# Codex: supports metadata block with short-description
_FRONTMATTER: dict[str, str] = {
    "cursor": (
        "---\n"
        "name: phalanx-orchestration\n"
        "description: "
        "Use when the user asks about phalanx, multi-agent, team of agents, "
        "sub-agents, spinning up agents, delegating tasks, parallelizing work, "
        "creating agent teams, orchestrating agents, running multiple agents, "
        "or any task that implies coordinating several AI agents. "
        "Provides phalanx CLI commands for agent team lifecycle management.\n"
        "---\n"
    ),
    "claude": (
        "---\n"
        "name: phalanx-orchestration\n"
        "description: Multi-agent orchestration via phalanx CLI. Use when the user asks to create a team, delegate tasks, spin up agents, or manage sub-agents.\n"
        "---\n"
    ),
    "gemini": (
        "---\n"
        "name: phalanx-orchestration\n"
        "description: Multi-agent orchestration via phalanx CLI. Use when the user asks to create a team, delegate tasks, spin up agents, or manage sub-agents in a multi-agent workflow.\n"
        "---\n"
    ),
    "codex": (
        "---\n"
        "name: phalanx-orchestration\n"
        "description: Multi-agent orchestration via phalanx CLI — create teams, delegate tasks, manage sub-agents.\n"
        "metadata:\n"
        "  short-description: Manage multi-agent teams in Phalanx\n"
        "---\n"
    ),
}

_DEFAULT_FRONTMATTER = _FRONTMATTER["cursor"]

# Cursor .mdc rule frontmatter — uses alwaysApply so it's injected on every turn.
# Workaround for Cursor CLI TUI mode not loading skills (agentSkill toolType omitted).
_CURSOR_RULE_FRONTMATTER = (
    "---\n"
    "description: "
    "Phalanx multi-agent orchestration — create teams, delegate tasks, "
    "spin up sub-agents, parallelize work.\n"
    "alwaysApply: true\n"
    "---\n"
)


def _load_skill_body() -> str:
    return (SOUL_DIR / "skill_body.md").read_text()


def load_skill(backend: str | None = None) -> str:
    """Load the phalanx skill with CLI-specific frontmatter."""
    frontmatter = _FRONTMATTER.get(backend, _DEFAULT_FRONTMATTER) if backend else _DEFAULT_FRONTMATTER
    return frontmatter + "\n" + _load_skill_body()


def load_cursor_rule() -> str:
    """Load the phalanx content as a Cursor .mdc rule with alwaysApply: true."""
    return _CURSOR_RULE_FRONTMATTER + "\n" + _load_skill_body()


def load_soul(name: str, **variables: str) -> str:
    """Load a soul file and inject dynamic variables."""
    path = SOUL_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Soul file not found: {path}")

    content = path.read_text()
    for key, value in variables.items():
        content = content.replace(f"{{{key}}}", value)
    return content


def load_team_lead_soul(worker_list: str, team_task: str) -> str:
    return load_soul("team_lead", worker_list=worker_list, team_task=team_task)


def load_worker_soul(task: str) -> str:
    return load_soul("worker", task=task)


def write_soul_to_temp(content: str, team_dir: Path, agent_id: str) -> Path:
    """Write a soul file to the team's temp directory. Returns the path."""
    soul_dir = team_dir / "souls"
    soul_dir.mkdir(parents=True, exist_ok=True)
    path = soul_dir / f"{agent_id}.md"
    path.write_text(content)
    return path
