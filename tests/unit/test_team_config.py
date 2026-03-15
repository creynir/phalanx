"""Tests for team config parsing and validation."""

from __future__ import annotations


import pytest

from phalanx.team.config import (
    AgentSpec,
    LeadSpec,
    TeamConfig,
    load_team_config,
    parse_team_config,
    resolve_backend_for_role,
    resolve_model,
    validate_team_models,
)


class TestResolveModel:
    def test_explicit_model_wins(self):
        assert resolve_model("cursor", "coder", "gpt-4") == "gpt-4"

    def test_role_default(self):
        model = resolve_model("cursor", "coder")
        assert model == "sonnet-4.6"

    def test_unknown_backend_falls_back(self):
        model = resolve_model("unknown-backend", "coder")
        assert isinstance(model, str)

    def test_lead_role(self):
        model = resolve_model("claude", "lead")
        assert model == "claude-sonnet-4-20250514"

    def test_codex_defaults_to_gpt_5_4(self):
        model = resolve_model("codex", "lead")
        assert model == "gpt-5.4"


class TestResolveBackendForRole:
    def test_role_override_wins(self):
        backend = resolve_backend_for_role(
            role="coder",
            default_backend="cursor",
            backend_overrides={"coder": "codex", "worker": "claude"},
        )
        assert backend == "codex"

    def test_worker_override_used_for_worker_roles(self):
        backend = resolve_backend_for_role(
            role="reviewer",
            default_backend="cursor",
            backend_overrides={"worker": "codex"},
        )
        assert backend == "codex"

    def test_falls_back_to_default(self):
        backend = resolve_backend_for_role(
            role="lead",
            default_backend="cursor",
            backend_overrides={"worker": "codex"},
        )
        assert backend == "cursor"


class TestAgentSpec:
    def test_valid_agent(self):
        spec = AgentSpec(name="reviewer", role="reviewer", prompt="Review the code")
        assert spec.name == "reviewer"
        assert spec.role == "reviewer"

    def test_invalid_role_raises(self):
        with pytest.raises(ValueError, match="Invalid role"):
            AgentSpec(name="x", role="invalid", prompt="do stuff")

    def test_empty_prompt_raises(self):
        with pytest.raises(ValueError, match="non-empty prompt"):
            AgentSpec(name="x", role="coder", prompt="")

    def test_generate_id(self):
        spec = AgentSpec(name="auth-reviewer", role="reviewer", prompt="review auth")
        spec.generate_id()
        assert spec.agent_id.startswith("auth-reviewer-")
        assert len(spec.agent_id) == len("auth-reviewer-") + 8

    def test_resolve_model(self):
        spec = AgentSpec(name="x", role="coder", prompt="task", model="my-model")
        assert spec.resolve_model("cursor") == "my-model"

    def test_to_dict(self):
        spec = AgentSpec(name="x", role="coder", prompt="task")
        spec.generate_id()
        d = spec.to_dict()
        assert d["name"] == "x"
        assert d["role"] == "coder"
        assert d["prompt"] == "task"
        assert d["agent_id"].startswith("x-")


class TestTeamConfig:
    def test_valid_config(self):
        tc = TeamConfig(
            task="build auth module",
            agents=[AgentSpec(name="coder", role="coder", prompt="code auth")],
        )
        assert tc.task == "build auth module"

    def test_empty_task_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            TeamConfig(task="", agents=[AgentSpec(name="x", role="coder", prompt="y")])

    def test_no_agents_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            TeamConfig(task="do stuff", agents=[])

    def test_generate_ids(self):
        tc = TeamConfig(
            task="task",
            agents=[
                AgentSpec(name="a", role="coder", prompt="p1"),
                AgentSpec(name="b", role="reviewer", prompt="p2"),
            ],
        )
        tc.generate_ids()
        assert tc.lead.agent_id.startswith("team-lead-")
        assert tc.agents[0].agent_id.startswith("a-")
        assert tc.agents[1].agent_id.startswith("b-")

    def test_to_dict(self):
        tc = TeamConfig(
            task="task",
            agents=[AgentSpec(name="a", role="coder", prompt="p")],
        )
        tc.generate_ids()
        d = tc.to_dict()
        assert d["task"] == "task"
        assert len(d["agents"]) == 1
        assert d["lead"]["name"] == "team-lead"

    def test_save_and_load(self, tmp_path):
        tc = TeamConfig(
            task="build stuff",
            lead=LeadSpec(name="boss", model="opus"),
            agents=[
                AgentSpec(name="dev", role="coder", prompt="write code"),
                AgentSpec(name="qa", role="reviewer", prompt="review code"),
            ],
        )
        tc.generate_ids()
        config_path = tmp_path / "team.json"
        tc.save(config_path)

        loaded = load_team_config(config_path)
        assert loaded.task == "build stuff"
        assert loaded.lead.name == "boss"
        assert loaded.lead.model == "opus"
        assert len(loaded.agents) == 2
        assert loaded.agents[0].name == "dev"
        assert loaded.agents[1].name == "qa"


class TestParseTeamConfig:
    def test_parse_full(self):
        data = {
            "task": "refactor auth",
            "lead": {"name": "lead", "model": "opus"},
            "agents": [
                {"name": "dev", "role": "coder", "prompt": "code it"},
                {"name": "qa", "role": "reviewer", "prompt": "review it", "model": "sonnet"},
            ],
        }
        tc = parse_team_config(data)
        assert tc.task == "refactor auth"
        assert tc.lead.name == "lead"
        assert len(tc.agents) == 2
        assert tc.agents[1].model == "sonnet"

    def test_parse_minimal(self):
        data = {
            "task": "fix bug",
            "agents": [{"name": "dev", "role": "coder", "prompt": "fix it"}],
        }
        tc = parse_team_config(data)
        assert tc.lead.name == "team-lead"
        assert tc.lead.model is None

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_team_config(tmp_path / "nonexistent.json")


def test_validate_team_models_uses_backend_overrides():
    tc = TeamConfig(
        task="mixed backend",
        agents=[AgentSpec(name="dev", role="coder", prompt="do", model="o3")],
        lead=LeadSpec(model="gpt-4.1"),
    )
    validate_team_models(
        tc,
        default_backend="cursor",
        backend_overrides={"worker": "codex", "lead": "codex"},
    )


def test_validate_team_models_accepts_mixed_cursor_and_codex_models():
    tc = TeamConfig(
        task="mixed backend explicit models",
        agents=[
            AgentSpec(
                name="worker",
                role="coder",
                prompt="do",
                model="composer-1.5",
            )
        ],
        lead=LeadSpec(model="gpt-5.4"),
    )
    validate_team_models(
        tc,
        default_backend="cursor",
        backend_overrides={"worker": "cursor", "lead": "codex"},
    )


def test_validate_team_models_does_not_reject_unknown_model_strings():
    tc = TeamConfig(
        task="runtime model fallback",
        agents=[AgentSpec(name="dev", role="coder", prompt="do", model="some-future-model")],
        lead=LeadSpec(model="another-unknown-model"),
    )
    validate_team_models(
        tc,
        default_backend="cursor",
        backend_overrides={"worker": "codex", "lead": "claude"},
    )


def test_validate_team_models_still_rejects_unknown_backends():
    tc = TeamConfig(
        task="invalid backend",
        agents=[AgentSpec(name="dev", role="coder", prompt="do", backend="nope")],
    )
    with pytest.raises(ValueError, match="Unknown backend"):
        validate_team_models(tc, default_backend="cursor")
