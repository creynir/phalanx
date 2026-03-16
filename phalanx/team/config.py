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


# ---------------------------------------------------------------------------
# V2 schema — new format, no migration path from v1
# ---------------------------------------------------------------------------

_V2_VALID_BACKENDS = {"cursor", "claude", "gemini", "codex"}

# V1 fields that must not appear in a v2 config, with a helpful hint for each.
_V2_FORBIDDEN_TOP_LEVEL = {
    "task": (
        "'task' is a v1 field. In v2, move the task description into 'lead.prompt'. "
        "Please migrate your config to v2 format."
    ),
    "idle_timeout_seconds": (
        "'idle_timeout_seconds' is a v1 field. In v2, use 'idle_timeout' instead. "
        "Please migrate your config to v2 format."
    ),
    "max_runtime_seconds": (
        "'max_runtime_seconds' is a v1 field. In v2, use 'max_runtime' instead. "
        "Please migrate your config to v2 format."
    ),
}

_V2_FORBIDDEN_LEAD = {
    "name": (
        "'name' on lead is a v1 field and has been removed in v2. "
        "Please migrate your config to v2 format."
    ),
}

_V2_FORBIDDEN_AGENT = {
    "name": (
        "'name' on agents is a v1 field and has been removed in v2. "
        "Please migrate your config to v2 format."
    ),
    "role": (
        "'role' on agents is a v1 field and has been removed in v2. "
        "Please migrate your config to v2 format."
    ),
}


@dataclass
class V2AgentSpec:
    """A single agent in a v2 team config."""

    model: str
    prompt: str
    backend: str | None = None
    soul: str | None = None


@dataclass
class V2LeadSpec:
    """The team lead in a v2 team config."""

    model: str
    prompt: str
    backend: str | None = None
    soul: str | None = None


@dataclass
class V2TeamConfig:
    """Full team configuration for the v2 schema."""

    lead: V2LeadSpec
    agents: list[V2AgentSpec]
    idle_timeout: int = 1800
    max_runtime: int = 1800


def _v2_check_backend(backend: str | None, context: str) -> None:
    """Raise ValueError if *backend* is set but is not a known v2 backend.

    An empty string is treated as an invalid backend (not as "unset").
    Pass ``None`` to express "no backend specified".
    """
    if backend is None:
        return
    if not backend or backend not in _V2_VALID_BACKENDS:
        raise ValueError(
            f"Invalid backend {backend!r} in {context}. "
            f"Must be one of: {', '.join(sorted(_V2_VALID_BACKENDS))}."
        )


def _v2_check_soul(soul: str | None, context: str) -> None:
    """Raise ValueError if *soul* is set but the file does not exist on disk."""
    if soul is None:
        return
    if not Path(soul).exists():
        raise ValueError(
            f"Soul file not found for {context}: {soul!r}. "
            "Ensure the path is correct and the file exists."
        )


def validate_v2_config(data: dict) -> None:
    """Validate a v2 team config dict.

    Raises ValueError (or KeyError for missing required keys) with a
    human-readable message for every hard validation rule. Returns None
    on success.
    """
    # Rule 9 — reject v1 top-level fields immediately with migration hints.
    for field_name, msg in _V2_FORBIDDEN_TOP_LEVEL.items():
        if field_name in data:
            raise ValueError(msg)

    # Rule 2 — lead must be present.
    if "lead" not in data:
        raise ValueError("'lead' key is required in v2 team config.")
    lead_data: dict = data["lead"]

    # Rule 9 — reject v1 lead fields.
    for field_name, msg in _V2_FORBIDDEN_LEAD.items():
        if field_name in lead_data:
            raise ValueError(msg)

    # Rule 3 — lead.prompt must be present and non-empty (not whitespace-only).
    lead_prompt = lead_data.get("prompt")
    if lead_prompt is None or not str(lead_prompt).strip():
        raise ValueError(
            "lead.prompt is required and must be a non-empty, non-whitespace string."
        )

    # Rule 4 — lead.model must be present.
    if "model" not in lead_data or lead_data["model"] is None:
        raise ValueError("lead.model is required in v2 team config.")

    # Rule 8 — lead.backend must be a known value if provided.
    # Pass the raw value; _v2_check_backend treats empty string as invalid too.
    _v2_check_backend(lead_data.get("backend"), "lead")

    # Soul validation for lead.
    _v2_check_soul(lead_data.get("soul"), "lead")

    # Rule 5 — agents must be present and non-empty.
    if "agents" not in data:
        raise ValueError("'agents' key is required in v2 team config.")
    agents_data = data["agents"]
    if not agents_data:
        raise ValueError(
            "v2 team config must have at least one agent in 'agents'."
        )

    # Rule 6 — per-agent validation.
    for idx, agent_data in enumerate(agents_data):
        label = f"agents[{idx}]"

        # Rule 9 — reject v1 agent fields.
        for field_name, msg in _V2_FORBIDDEN_AGENT.items():
            if field_name in agent_data:
                raise ValueError(msg)

        # prompt must be present and non-empty.
        agent_prompt = agent_data.get("prompt")
        if agent_prompt is None or not str(agent_prompt).strip():
            raise ValueError(
                f"{label}.prompt is required and must be a non-empty, "
                "non-whitespace string."
            )

        # model must be present.
        if "model" not in agent_data or agent_data["model"] is None:
            raise ValueError(f"{label}.model is required in v2 team config.")

        # Rule 8 — backend must be a known value if provided.
        # Pass the raw value; _v2_check_backend treats empty string as invalid too.
        _v2_check_backend(agent_data.get("backend"), label)

        # Soul validation.
        _v2_check_soul(agent_data.get("soul"), label)


def parse_team_config_v2(data: dict) -> V2TeamConfig:
    """Parse and validate a v2 team config dict, returning a V2TeamConfig."""
    validate_v2_config(data)

    lead_data = data["lead"]
    lead = V2LeadSpec(
        model=lead_data["model"],
        prompt=lead_data["prompt"],
        backend=lead_data.get("backend") or None,
        soul=lead_data.get("soul") or None,
    )

    agents = [
        V2AgentSpec(
            model=agent_data["model"],
            prompt=agent_data["prompt"],
            backend=agent_data.get("backend") or None,
            soul=agent_data.get("soul") or None,
        )
        for agent_data in data["agents"]
    ]

    return V2TeamConfig(
        lead=lead,
        agents=agents,
        idle_timeout=int(data.get("idle_timeout", 1800)),
        max_runtime=int(data.get("max_runtime", 1800)),
    )


def load_team_config_v2(path: Path) -> V2TeamConfig:
    """Load a v2 team config from a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"V2 team config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_team_config_v2(data)


def v2_to_v1_team_config(v2: V2TeamConfig, task: str = "") -> TeamConfig:
    """Convert a V2TeamConfig into a V1 TeamConfig.

    V2 has no per-agent name/role, so synthetic values are generated:
    * role defaults to "coder" for workers
    * name is auto-generated from the index
    The task is taken from the lead prompt when not provided explicitly.
    """
    effective_task = task or v2.lead.prompt

    lead = LeadSpec(
        name="team-lead",
        model=v2.lead.model,
        backend=v2.lead.backend,
    )

    agents = []
    for idx, spec in enumerate(v2.agents):
        agents.append(
            AgentSpec(
                name=f"agent-{idx}",
                role="coder",
                prompt=spec.prompt,
                model=spec.model,
                backend=spec.backend,
            )
        )

    return TeamConfig(task=effective_task, agents=agents, lead=lead)
