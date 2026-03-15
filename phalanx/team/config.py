"""Team configuration schema: parsing, validation, and defaults.

The Main Agent writes a JSON config file defining the team structure.
Each agent gets a unique prompt, name, role, and model. The team lead
is auto-spawned with optional name/model overrides.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path


VALID_ROLES = {"researcher", "coder", "reviewer", "architect"}

DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "cursor": {
        "default": "sonnet-4.6",
        "researcher": "sonnet-4.6",
        "coder": "sonnet-4.6",
        "reviewer": "sonnet-4.6",
        "architect": "opus-4.6",
        "lead": "sonnet-4.6",
    },
    "claude": {
        "default": "claude-sonnet-4-20250514",
        "researcher": "claude-sonnet-4-20250514",
        "coder": "claude-sonnet-4-20250514",
        "reviewer": "claude-sonnet-4-20250514",
        "architect": "claude-opus-4-20250514",
        "lead": "claude-sonnet-4-20250514",
    },
    "gemini": {
        "default": "gemini-2.5-pro",
        "researcher": "gemini-2.5-flash",
        "coder": "gemini-2.5-pro",
        "reviewer": "gemini-2.5-pro",
        "architect": "gemini-2.5-pro",
        "lead": "gemini-2.5-pro",
    },
    "codex": {
        "default": "gpt-5.4",
        "researcher": "gpt-5.4",
        "coder": "gpt-5.4",
        "reviewer": "gpt-5.4",
        "architect": "gpt-5.4",
        "lead": "gpt-5.4",
    },
}


def _gen_id(name: str) -> str:
    return f"{name}-{uuid.uuid4().hex[:8]}"


def resolve_backend_for_role(
    role: str,
    default_backend: str,
    backend_overrides: dict[str, str] | None = None,
) -> str:
    """Resolve backend for a role using optional overrides.

    Priority: role override > generic worker override (for worker roles)
    > default backend.
    """
    overrides = backend_overrides or {}
    if role in overrides and overrides[role]:
        return overrides[role]
    if role in VALID_ROLES and overrides.get("worker"):
        return overrides["worker"]
    return default_backend


def resolve_model(backend: str, role: str, explicit_model: str | None = None) -> str:
    """Resolve the model for a given backend and role.

    Priority: explicit_model > role-specific default > backend default.
    """
    if explicit_model:
        return explicit_model
    backend_models = DEFAULT_MODELS.get(backend, DEFAULT_MODELS["cursor"])
    return backend_models.get(role, backend_models["default"])


@dataclass
class AgentSpec:
    """Specification for a single agent in the team."""

    name: str
    role: str
    prompt: str
    model: str | None = None
    worktree: str | None = None
    backend: str | None = None

    # Generated at creation time
    agent_id: str = ""

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{self.role}' for agent '{self.name}'. "
                f"Valid roles: {', '.join(sorted(VALID_ROLES))}"
            )
        if not self.prompt:
            raise ValueError(f"Agent '{self.name}' must have a non-empty prompt")

    def generate_id(self) -> None:
        if not self.agent_id:
            self.agent_id = _gen_id(self.name)

    def resolve_model(self, backend: str) -> str:
        return resolve_model(backend, self.role, self.model)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "prompt": self.prompt,
            "model": self.model,
            "worktree": self.worktree,
            "backend": self.backend,
            "agent_id": self.agent_id,
        }


@dataclass
class LeadSpec:
    """Optional overrides for the auto-spawned team lead."""

    name: str = "team-lead"
    model: str | None = None
    backend: str | None = None

    agent_id: str = ""

    def generate_id(self) -> None:
        if not self.agent_id:
            self.agent_id = _gen_id(self.name)

    def resolve_model(self, backend: str) -> str:
        return resolve_model(backend, "lead", self.model)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "backend": self.backend,
            "agent_id": self.agent_id,
        }


@dataclass
class TeamConfig:
    """Full team configuration parsed from JSON."""

    task: str
    agents: list[AgentSpec] = field(default_factory=list)
    lead: LeadSpec = field(default_factory=LeadSpec)

    def __post_init__(self) -> None:
        if not self.task:
            raise ValueError("Team config must have a non-empty 'task'")
        if not self.agents:
            raise ValueError("Team config must have at least one agent")

    def generate_ids(self) -> None:
        self.lead.generate_id()
        for agent in self.agents:
            agent.generate_id()

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "lead": self.lead.to_dict(),
            "agents": [a.to_dict() for a in self.agents],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")


def parse_team_config(data: dict) -> TeamConfig:
    """Parse a team config from a dict (loaded from JSON)."""
    task = data.get("task", "")

    lead_data = data.get("lead", {})
    lead = LeadSpec(
        name=lead_data.get("name", "team-lead"),
        model=lead_data.get("model"),
        backend=lead_data.get("backend"),
    )

    agents = []
    for agent_data in data.get("agents", []):
        agents.append(
            AgentSpec(
                name=agent_data["name"],
                role=agent_data["role"],
                prompt=agent_data["prompt"],
                model=agent_data.get("model"),
                worktree=agent_data.get("worktree"),
                backend=agent_data.get("backend"),
            )
        )

    return TeamConfig(task=task, agents=agents, lead=lead)


def validate_team_models(
    team_config: TeamConfig,
    default_backend: str,
    backend_overrides: dict[str, str] | None = None,
) -> None:
    """Validate backend identity for team members.

    Model-name validation is intentionally skipped: model compatibility and
    fallback behavior are delegated to the backend CLI at runtime.
    """
    from phalanx.backends import get_backend

    for agent in team_config.agents:
        be = agent.backend or resolve_backend_for_role(
            agent.role, default_backend, backend_overrides
        )
        # Keep backend validation so unknown backend names fail early.
        get_backend(be)

    lead_be = team_config.lead.backend or resolve_backend_for_role(
        "lead", default_backend, backend_overrides
    )
    get_backend(lead_be)


def load_team_config(path: Path) -> TeamConfig:
    """Load a team config from a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Team config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_team_config(data)
