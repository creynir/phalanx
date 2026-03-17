"""Tests for team config parsing and validation.

This file covers BOTH the existing v1 API and the new v2 schema.
V2 tests are in the TestV2* classes.
"""

from __future__ import annotations

import json

import pytest

from phalanx.team.config import (
    AgentSpec,
    LeadSpec,
    TeamConfig,
    V2TeamConfig,
    load_team_config,
    load_team_config_v2,
    parse_team_config,
    parse_team_config_v2,
    resolve_backend_for_role,
    resolve_model,
    validate_team_models,
    validate_v2_config,
)


# ---------------------------------------------------------------------------
# Existing v1 tests — keep passing until v2 implementation replaces them
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# V2 schema tests
# ---------------------------------------------------------------------------


# ---- helper: a valid minimal v2 dict -----------------------------------

def _valid_v2() -> dict:
    return {
        "lead": {
            "backend": "codex",
            "model": "gpt-5.4",
            "prompt": "You are the lead. Coordinate the team.",
        },
        "agents": [
            {
                "backend": "cursor",
                "model": "auto",
                "prompt": "Write the feature.",
            }
        ],
        "idle_timeout": 300,
        "max_runtime": 1800,
    }


# ---- validate_v2_config direct-call tests ------------------------------


class TestValidateV2Config:
    """Direct coverage of validate_v2_config — green team needs this contract."""

    def test_validate_v2_config_happy_path(self):
        """validate_v2_config should not raise on a valid v2 dict."""
        validate_v2_config(_valid_v2())

    def test_validate_v2_config_raises_on_missing_lead(self):
        """validate_v2_config should raise when lead is absent."""
        data = _valid_v2()
        del data["lead"]
        with pytest.raises((ValueError, KeyError)):
            validate_v2_config(data)


# ---- happy-path tests --------------------------------------------------


class TestV2HappyPath:
    """Valid v2 configs should parse without errors."""

    def test_minimal_valid_v2_config_returns_v2teamconfig(self):
        """parse_team_config_v2 must return a V2TeamConfig instance."""
        cfg = parse_team_config_v2(_valid_v2())
        assert isinstance(cfg, V2TeamConfig)

    def test_lead_prompt_is_stored(self):
        cfg = parse_team_config_v2(_valid_v2())
        assert cfg.lead.prompt == "You are the lead. Coordinate the team."

    def test_agent_model_auto_is_valid(self):
        data = _valid_v2()
        data["agents"][0]["model"] = "auto"
        cfg = parse_team_config_v2(data)
        assert cfg.agents[0].model == "auto"

    def test_agent_model_arbitrary_string_is_valid(self):
        """Model strings are passed through; phalanx does not validate them."""
        data = _valid_v2()
        data["agents"][0]["model"] = "some-future-model-7b"
        cfg = parse_team_config_v2(data)
        assert cfg.agents[0].model == "some-future-model-7b"

    def test_model_sonnet_is_valid(self):
        data = _valid_v2()
        data["agents"][0]["model"] = "sonnet"
        cfg = parse_team_config_v2(data)
        assert cfg.agents[0].model == "sonnet"

    def test_idle_timeout_and_max_runtime_stored(self):
        cfg = parse_team_config_v2(_valid_v2())
        assert cfg.idle_timeout == 300
        assert cfg.max_runtime == 1800

    def test_idle_timeout_and_max_runtime_optional(self):
        data = _valid_v2()
        del data["idle_timeout"]
        del data["max_runtime"]
        cfg = parse_team_config_v2(data)
        assert cfg is not None

    def test_multiple_agents_accepted(self):
        data = _valid_v2()
        data["agents"].append(
            {"backend": "claude", "model": "sonnet", "prompt": "Review the PR."}
        )
        cfg = parse_team_config_v2(data)
        assert len(cfg.agents) == 2

    def test_no_name_field_on_agent(self):
        """V2 agents have no 'name' field — attribute must be None or absent."""
        cfg = parse_team_config_v2(_valid_v2())
        assert getattr(cfg.agents[0], "name", None) is None

    def test_no_role_field_on_agent(self):
        """V2 agents have no 'role' field — attribute must be None or absent."""
        cfg = parse_team_config_v2(_valid_v2())
        assert getattr(cfg.agents[0], "role", None) is None

    def test_backend_optional_on_agent(self):
        """Backend is optional on agents."""
        data = _valid_v2()
        del data["agents"][0]["backend"]
        cfg = parse_team_config_v2(data)
        assert cfg is not None

    def test_backend_optional_on_lead(self):
        data = _valid_v2()
        del data["lead"]["backend"]
        cfg = parse_team_config_v2(data)
        assert cfg is not None

    def test_all_valid_backends_accepted(self):
        for backend in ("cursor", "claude", "gemini", "codex"):
            data = _valid_v2()
            data["lead"]["backend"] = backend
            data["agents"][0]["backend"] = backend
            cfg = parse_team_config_v2(data)
            assert cfg is not None, f"backend {backend!r} should be accepted"


# ---- soul field tests --------------------------------------------------


class TestV2SoulField:
    """Soul resolution: optional field, file must exist if specified."""

    def test_soul_absent_on_lead_is_none(self):
        """When 'soul' is not in lead config, parsed lead.soul is None."""
        data = _valid_v2()
        assert "soul" not in data["lead"]
        cfg = parse_team_config_v2(data)
        assert cfg.lead.soul is None

    def test_soul_absent_on_agent_is_none(self):
        """When 'soul' is not in agent config, parsed agent.soul is None."""
        data = _valid_v2()
        assert "soul" not in data["agents"][0]
        cfg = parse_team_config_v2(data)
        assert cfg.agents[0].soul is None

    def test_lead_soul_path_that_exists_is_stored(self, tmp_path):
        soul_file = tmp_path / "lead_soul.md"
        soul_file.write_text("# Lead soul")
        data = _valid_v2()
        data["lead"]["soul"] = str(soul_file)
        cfg = parse_team_config_v2(data)
        assert cfg.lead.soul == str(soul_file)

    def test_agent_soul_path_that_exists_is_stored(self, tmp_path):
        soul_file = tmp_path / "agent_soul.md"
        soul_file.write_text("# Agent soul")
        data = _valid_v2()
        data["agents"][0]["soul"] = str(soul_file)
        cfg = parse_team_config_v2(data)
        assert cfg.agents[0].soul == str(soul_file)

    def test_lead_soul_path_not_found_raises(self, tmp_path):
        """If soul path is specified but the file is missing → hard error."""
        data = _valid_v2()
        data["lead"]["soul"] = str(tmp_path / "nonexistent_soul.md")
        with pytest.raises((ValueError, FileNotFoundError)):
            parse_team_config_v2(data)

    def test_agent_soul_path_not_found_raises(self, tmp_path):
        data = _valid_v2()
        data["agents"][0]["soul"] = str(tmp_path / "ghost.md")
        with pytest.raises((ValueError, FileNotFoundError)):
            parse_team_config_v2(data)


# ---- validation error tests -------------------------------------------


class TestV2ValidationErrors:
    """Every hard validation rule should raise a clear error."""

    def test_missing_lead_raises(self):
        """Rule 2: lead key must be present."""
        data = _valid_v2()
        del data["lead"]
        with pytest.raises((ValueError, KeyError)):
            parse_team_config_v2(data)

    def test_missing_lead_prompt_raises(self):
        """Rule 3: lead.prompt must be present and non-empty."""
        data = _valid_v2()
        del data["lead"]["prompt"]
        with pytest.raises(ValueError, match="(?i)lead.*prompt|prompt.*lead"):
            parse_team_config_v2(data)

    def test_empty_lead_prompt_raises(self):
        data = _valid_v2()
        data["lead"]["prompt"] = ""
        with pytest.raises(ValueError, match="(?i)lead.*prompt|prompt.*lead|non.?empty"):
            parse_team_config_v2(data)

    def test_whitespace_only_lead_prompt_raises(self):
        """Whitespace-only prompt is treated as empty and must be rejected."""
        data = _valid_v2()
        data["lead"]["prompt"] = "   "
        with pytest.raises(ValueError, match="(?i)prompt|non.?empty"):
            parse_team_config_v2(data)

    def test_missing_lead_model_raises(self):
        """Rule 4: lead.model must be present."""
        data = _valid_v2()
        del data["lead"]["model"]
        with pytest.raises(ValueError, match="(?i)model"):
            parse_team_config_v2(data)

    def test_empty_agents_list_raises(self):
        """Rule 5: agents must be a non-empty list."""
        data = _valid_v2()
        data["agents"] = []
        with pytest.raises(ValueError, match="(?i)agent"):
            parse_team_config_v2(data)

    def test_missing_agents_key_raises(self):
        data = _valid_v2()
        del data["agents"]
        with pytest.raises((ValueError, KeyError)):
            parse_team_config_v2(data)

    def test_agent_missing_prompt_raises(self):
        """Rule 6: each agent must have a non-empty prompt (first agent)."""
        data = _valid_v2()
        del data["agents"][0]["prompt"]
        with pytest.raises(ValueError, match="(?i)prompt"):
            parse_team_config_v2(data)

    def test_agent_empty_prompt_raises(self):
        data = _valid_v2()
        data["agents"][0]["prompt"] = ""
        with pytest.raises(ValueError, match="(?i)prompt|non.?empty"):
            parse_team_config_v2(data)

    def test_whitespace_only_agent_prompt_raises(self):
        """Whitespace-only agent prompt is treated as empty and must be rejected."""
        data = _valid_v2()
        data["agents"][0]["prompt"] = "   "
        with pytest.raises(ValueError, match="(?i)prompt|non.?empty"):
            parse_team_config_v2(data)

    def test_second_agent_missing_prompt_raises(self):
        """Validation must check every agent, not just the first."""
        data = _valid_v2()
        data["agents"].append({"backend": "claude", "model": "sonnet", "prompt": ""})
        with pytest.raises(ValueError, match="(?i)prompt|non.?empty"):
            parse_team_config_v2(data)

    def test_agent_missing_model_raises(self):
        """Rule 6: each agent must have model."""
        data = _valid_v2()
        del data["agents"][0]["model"]
        with pytest.raises(ValueError, match="(?i)model"):
            parse_team_config_v2(data)

    def test_invalid_backend_on_lead_raises(self):
        """Rule 8: backend must be one of cursor/claude/gemini/codex."""
        data = _valid_v2()
        data["lead"]["backend"] = "openai"
        with pytest.raises(ValueError, match="(?i)backend"):
            parse_team_config_v2(data)

    def test_empty_string_backend_on_lead_raises(self):
        """Empty-string backend is not a valid backend identifier."""
        data = _valid_v2()
        data["lead"]["backend"] = ""
        with pytest.raises(ValueError, match="(?i)backend"):
            parse_team_config_v2(data)

    def test_invalid_backend_on_agent_raises(self):
        data = _valid_v2()
        data["agents"][0]["backend"] = "unknown-backend"
        with pytest.raises(ValueError, match="(?i)backend"):
            parse_team_config_v2(data)

    def test_invalid_backend_error_message_lists_valid_options(self):
        """Error should mention at least one valid backend."""
        data = _valid_v2()
        data["agents"][0]["backend"] = "not-a-backend"
        with pytest.raises(ValueError) as exc_info:
            parse_team_config_v2(data)
        msg = str(exc_info.value).lower()
        assert any(b in msg for b in ("cursor", "claude", "gemini", "codex")), (
            f"Error message should list valid backends, got: {exc_info.value}"
        )


# ---- backward-incompatibility (v1 fields) tests -----------------------


class TestV2RejectsV1Fields:
    """Rule 9: old v1 fields must raise clear migration errors."""

    def test_top_level_task_field_raises(self):
        """V1 had a top-level 'task' key; v2 removes it."""
        data = _valid_v2()
        data["task"] = "some old task string"
        with pytest.raises(ValueError, match="(?i)task|migrate|v1|v2"):
            parse_team_config_v2(data)

    def test_agent_role_field_raises(self):
        """V1 agents had a 'role' field; v2 removes it."""
        data = _valid_v2()
        data["agents"][0]["role"] = "coder"
        with pytest.raises(ValueError, match="(?i)role|migrate|v1|v2"):
            parse_team_config_v2(data)

    def test_agent_name_field_raises(self):
        """V1 agents had a 'name' field; v2 removes it."""
        data = _valid_v2()
        data["agents"][0]["name"] = "my-coder"
        with pytest.raises(ValueError, match="(?i)name|migrate|v1|v2"):
            parse_team_config_v2(data)

    def test_lead_name_field_raises(self):
        """V1 lead had a 'name' field; v2 removes it."""
        data = _valid_v2()
        data["lead"]["name"] = "my-lead"
        with pytest.raises(ValueError, match="(?i)name|migrate|v1|v2"):
            parse_team_config_v2(data)

    def test_idle_timeout_seconds_raises(self):
        """V1 used 'idle_timeout_seconds'; v2 uses 'idle_timeout'."""
        data = _valid_v2()
        data["idle_timeout_seconds"] = 300
        with pytest.raises(ValueError, match="(?i)idle_timeout_seconds|migrate|v1|v2"):
            parse_team_config_v2(data)

    def test_max_runtime_seconds_raises(self):
        """V1 used 'max_runtime_seconds'; v2 uses 'max_runtime'."""
        data = _valid_v2()
        data["max_runtime_seconds"] = 1800
        with pytest.raises(ValueError, match="(?i)max_runtime_seconds|migrate|v1|v2"):
            parse_team_config_v2(data)

    def test_v1_migration_error_message_is_helpful(self):
        """Error message should tell the user to migrate to v2."""
        data = _valid_v2()
        data["task"] = "old task"
        with pytest.raises(ValueError) as exc_info:
            parse_team_config_v2(data)
        msg = str(exc_info.value).lower()
        assert "v2" in msg or "migrat" in msg, (
            f"Error should mention v2 or migration, got: {exc_info.value}"
        )


# ---- file-based loading tests -----------------------------------------


class TestV2LoadFromFile:
    """load_team_config_v2(path) should read a JSON file and return V2TeamConfig."""

    def test_load_valid_v2_json_file(self, tmp_path):
        config_file = tmp_path / "team_v2.json"
        config_file.write_text(json.dumps(_valid_v2()))
        cfg = load_team_config_v2(config_file)
        assert isinstance(cfg, V2TeamConfig)

    def test_load_v2_unparseable_json_raises(self, tmp_path):
        """Rule 1: JSON must be parseable — load_team_config_v2 should surface this."""
        config_file = tmp_path / "broken.json"
        config_file.write_text("{broken json]]]")
        with pytest.raises((json.JSONDecodeError, ValueError)):
            load_team_config_v2(config_file)

    def test_load_v2_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_team_config_v2(tmp_path / "no_such_file.json")
