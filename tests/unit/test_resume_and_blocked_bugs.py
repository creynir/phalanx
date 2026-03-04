"""Tests explicitly catching the two CLI bugs fixed in this sprint:

Bug 1: `phalanx resume` only woke up the Lead agent — workers were left dead.
Bug 2: `phalanx message-agent` and `phalanx resume-agent` rejected
       agents in the `blocked_on_prompt` state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from phalanx.cli import cli
from phalanx.db import StateDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "test.db")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def team_with_dead_workers(tmp_path):
    """A team whose lead AND two workers are all dead."""
    _db = StateDB(db_path=tmp_path / "test.db")
    _db.create_team("team-abc", "do some work")
    _db.create_agent("lead-001", "team-abc", "lead task", role="lead", backend="cursor")
    _db.create_agent("worker-001", "team-abc", "coder task", role="coder", backend="cursor")
    _db.create_agent("worker-002", "team-abc", "architect task", role="architect", backend="cursor")

    for agent_id in ("lead-001", "worker-001", "worker-002"):
        _db.update_agent(agent_id, status="dead")

    return tmp_path, "team-abc", _db


@pytest.fixture
def blocked_agent(tmp_path):
    """A single agent in blocked_on_prompt state."""
    _db = StateDB(db_path=tmp_path / "test.db")
    _db.create_team("team-xyz", "some task")
    _db.create_agent("agent-blocked", "team-xyz", "worker task", role="coder", backend="cursor")
    _db.update_agent("agent-blocked", status="blocked_on_prompt")
    return tmp_path, "agent-blocked", _db


# ---------------------------------------------------------------------------
# Bug 1: resume must wake ALL dead agents, not just the lead
# ---------------------------------------------------------------------------


class TestResumeBug:
    """Bug 1: phalanx resume <team_id> should wake ALL dead agents."""

    def test_resume_calls_resume_all_true_by_default(self, runner, db, tmp_path):
        """The CLI must pass resume_all=True to resume_team() without any flags."""
        db.create_team("team-t1", "task")
        db.create_agent("lead-t1", "team-t1", "lead task", role="lead")

        with (
            patch("phalanx.cli._get_db", return_value=db),
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config") as mock_cfg,
            patch("phalanx.process.manager.ProcessManager"),
            patch("phalanx.monitor.heartbeat.HeartbeatMonitor"),
            patch("phalanx.team.orchestrator.resume_team") as mock_resume,
        ):
            mock_cfg.return_value = MagicMock(idle_timeout_seconds=1800)
            mock_resume.return_value = {"team_id": "team-t1", "resumed_agents": ["lead-t1"]}

            result = runner.invoke(cli, ["resume", "team-t1"])

        assert result.exit_code == 0, result.output
        mock_resume.assert_called_once()
        _, kwargs = mock_resume.call_args
        assert kwargs.get("resume_all") is True, (
            "resume_team() must be called with resume_all=True by default — "
            "Bug 1: workers were left dead because resume_all defaulted to False"
        )

    def test_resume_wakes_workers_not_just_lead(self, runner, team_with_dead_workers):
        """All dead agents (lead + workers) must be woken up by resume."""
        tmp_path, team_id, _db = team_with_dead_workers

        captured_resume_all: dict = {}

        def fake_resume_team(**kwargs):
            captured_resume_all["value"] = kwargs.get("resume_all")
            return {"team_id": team_id, "resumed_agents": []}

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config") as mock_cfg,
            patch("phalanx.cli._get_db", return_value=_db),
            patch("phalanx.team.orchestrator.resume_team", side_effect=fake_resume_team),
        ):
            mock_cfg.return_value = MagicMock(idle_timeout_seconds=1800)
            result = runner.invoke(cli, ["resume", team_id])

        assert result.exit_code == 0, result.output
        assert captured_resume_all.get("value") is True, (
            "Bug 1 regression: resume_all must be True so workers are also woken up"
        )

    def test_lead_only_flag_passes_resume_all_false(self, runner, db, tmp_path):
        """The --lead-only flag must pass resume_all=False (leads only)."""
        db.create_team("team-lo", "task")
        db.create_agent("lead-lo", "team-lo", "lead task", role="lead")

        with (
            patch("phalanx.cli._get_db", return_value=db),
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config") as mock_cfg,
            patch("phalanx.team.orchestrator.resume_team") as mock_resume,
        ):
            mock_cfg.return_value = MagicMock(idle_timeout_seconds=1800)
            mock_resume.return_value = {"team_id": "team-lo", "resumed_agents": []}

            result = runner.invoke(cli, ["resume", "--lead-only", "team-lo"])

        assert result.exit_code == 0, result.output
        _, kwargs = mock_resume.call_args
        assert kwargs.get("resume_all") is False, (
            "--lead-only must pass resume_all=False to limit resumption to the lead"
        )


# ---------------------------------------------------------------------------
# Bug 2: blocked_on_prompt agents must be interactable
# ---------------------------------------------------------------------------


class TestBlockedOnPromptBug:
    """Bug 2: message-agent and resume-agent must work for blocked_on_prompt agents."""

    def test_message_agent_blocked_on_prompt_is_allowed(self, runner, blocked_agent):
        """message-agent must succeed for blocked_on_prompt agents (live tmux pane)."""
        tmp_path, agent_id, _db = blocked_agent

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config"),
            patch("phalanx.cli._get_db", return_value=_db),
            patch("phalanx.process.manager.ProcessManager") as mock_pm_cls,
        ):
            mock_pm = MagicMock()
            mock_pm_cls.return_value = mock_pm
            mock_pm.send_keys.return_value = True

            result = runner.invoke(cli, ["message-agent", agent_id, "y"])

        assert result.exit_code == 0, (
            f"Bug 2 regression: message-agent must not reject blocked_on_prompt agents. "
            f"Output: {result.output}"
        )

    def test_message_agent_dead_agent_is_still_rejected(self, runner, tmp_path):
        """message-agent must still fail for dead agents — pane no longer exists."""
        _db = StateDB(db_path=tmp_path / "test.db")
        _db.create_team("team-dead", "task")
        _db.create_agent("agent-dead", "team-dead", "task", role="coder")
        _db.update_agent("agent-dead", status="dead")

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config"),
            patch("phalanx.cli._get_db", return_value=_db),
        ):
            result = runner.invoke(cli, ["message-agent", "agent-dead", "hello"])

        assert result.exit_code != 0, (
            "Dead agents must not receive messages — their tmux pane is gone"
        )

    def test_message_agent_suspended_agent_is_rejected(self, runner, tmp_path):
        """message-agent must still fail for suspended agents."""
        _db = StateDB(db_path=tmp_path / "test.db")
        _db.create_team("team-sus", "task")
        _db.create_agent("agent-sus", "team-sus", "task", role="coder")
        _db.update_agent("agent-sus", status="suspended")

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config"),
            patch("phalanx.cli._get_db", return_value=_db),
        ):
            result = runner.invoke(cli, ["message-agent", "agent-sus", "hello"])

        assert result.exit_code != 0

    def test_resume_agent_reply_flag_sends_keystrokes(self, runner, blocked_agent):
        """resume-agent --reply 'y' must send keystrokes to unblock a blocked agent."""
        tmp_path, agent_id, _db = blocked_agent

        captured_send_keys: list = []

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config") as mock_cfg,
            patch("phalanx.cli._get_db", return_value=_db),
            patch("phalanx.process.manager.ProcessManager") as mock_pm_cls,
        ):
            mock_cfg.return_value = MagicMock(idle_timeout_seconds=1800)
            mock_pm = MagicMock()
            mock_pm_cls.return_value = mock_pm
            mock_pm.send_keys.side_effect = (
                lambda aid, keys, enter=True: captured_send_keys.append((aid, keys)) or True
            )

            result = runner.invoke(cli, ["resume-agent", agent_id, "--reply", "y"])

        assert result.exit_code == 0, (
            f"Bug 2 regression: resume-agent --reply must succeed for blocked agents. "
            f"Output: {result.output}"
        )
        assert any(keys == "y" for _, keys in captured_send_keys), (
            "send_keys must be called with 'y' to answer the prompt"
        )

    def test_resume_agent_without_reply_fails_for_blocked(self, runner, blocked_agent):
        """resume-agent without --reply must fail clearly for blocked_on_prompt agents."""
        tmp_path, agent_id, _db = blocked_agent

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config") as mock_cfg,
            patch("phalanx.cli._get_db", return_value=_db),
        ):
            mock_cfg.return_value = MagicMock(idle_timeout_seconds=1800)
            result = runner.invoke(cli, ["resume-agent", agent_id])

        assert result.exit_code != 0, (
            "resume-agent without --reply must fail for blocked_on_prompt agents "
            "with a helpful hint"
        )
        combined = result.output or ""
        assert "reply" in combined.lower() or "blocked" in combined.lower(), (
            f"Error output must mention --reply or blocked status. Got: {result.output!r}"
        )

    def test_resume_agent_dead_agent_still_works_normally(self, runner, tmp_path):
        """resume-agent (no --reply) must still work for dead agents as before."""
        _db = StateDB(db_path=tmp_path / "test.db")
        _db.create_team("team-res", "task")
        _db.create_agent("agent-res", "team-res", "task", role="coder")
        _db.update_agent("agent-res", status="dead")

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config") as mock_cfg,
            patch("phalanx.cli._get_db", return_value=_db),
            patch("phalanx.team.orchestrator.resume_single_agent") as mock_rsa,
        ):
            mock_cfg.return_value = MagicMock(idle_timeout_seconds=1800)
            mock_rsa.return_value = {
                "agent_id": "agent-res",
                "team_id": "team-res",
                "status": "running",
            }
            result = runner.invoke(cli, ["resume-agent", "agent-res"])

        assert result.exit_code == 0, (
            f"resume-agent must still work normally for dead agents. Output: {result.output}"
        )


# ---------------------------------------------------------------------------
# Regression: message_agent status update after unblocking
# ---------------------------------------------------------------------------


class TestMessageAgentStatusUpdate:
    """After messaging a blocked_on_prompt agent, its status should become running."""

    def test_status_updated_to_running_after_unblock(self, runner, blocked_agent):
        """After successfully messaging a blocked agent, DB status must become running."""
        tmp_path, agent_id, _db = blocked_agent

        with (
            patch("phalanx.cli._get_root", return_value=tmp_path),
            patch("phalanx.cli._get_config"),
            patch("phalanx.cli._get_db", return_value=_db),
            patch("phalanx.process.manager.ProcessManager") as mock_pm_cls,
        ):
            mock_pm = MagicMock()
            mock_pm_cls.return_value = mock_pm
            mock_pm.send_keys.return_value = True

            result = runner.invoke(cli, ["message-agent", agent_id, "y"])

        assert result.exit_code == 0
        updated = _db.get_agent(agent_id)
        assert updated["status"] == "running", (
            "After unblocking via message-agent, agent status must be updated to 'running'"
        )
