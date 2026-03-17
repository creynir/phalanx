"""RED-team tests for Phase 5: completed status in CLI display + resume semantics.

All tests in this file are expected to FAIL before Phase 5 implementation.
They verify:
  1. resume_team() includes agents with status="completed"
  2. Resuming a completed agent clears artifact_status to None
  3. stop_team() kills agents in "completing" status
  4. CLI displays "stopped" for agents with status="completed"
  5. resume_team() accepts a team with status="completed"
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator_deps():
    """Return mocked collaborators for orchestrator functions."""
    db = MagicMock()
    pm = MagicMock()
    hm = MagicMock()
    return db, pm, hm


def _make_agent(
    agent_id: str,
    team_id: str = "team-1",
    status: str = "running",
    role: str = "worker",
    artifact_status: str | None = None,
    chat_id: str | None = None,
    backend: str = "cursor",
    task: str = "do something",
    model: str | None = None,
) -> dict:
    return {
        "id": agent_id,
        "team_id": team_id,
        "status": status,
        "role": role,
        "artifact_status": artifact_status,
        "chat_id": chat_id,
        "backend": backend,
        "task": task,
        "model": model,
        "updated_at": 0,
    }


# ---------------------------------------------------------------------------
# Test 1: resume_team includes completed agents
# ---------------------------------------------------------------------------

class TestResumeTeamIncludesCompletedAgents:
    """resume_team() must resume agents whose status is 'completed',
    not just 'dead' and 'suspended'."""

    def test_resume_team_includes_completed_agents(self, tmp_path):
        from phalanx.team.orchestrator import resume_team

        lead = _make_agent("lead-1", status="completed", role="lead", chat_id="sess-lead")
        worker = _make_agent("worker-1", status="completed", role="worker", chat_id="sess-worker")

        db, pm, hm = _make_orchestrator_deps()
        db.list_agents.return_value = [lead, worker]

        # spawn_resume returns a mock AgentProcess
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        pm.spawn_resume.return_value = mock_proc

        with patch("phalanx.backends.get_backend") as mock_gb, \
             patch("phalanx.team.create._spawn_team_monitor"):
            mock_gb.return_value = MagicMock()

            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=pm,
                heartbeat_monitor=hm,
                team_id="team-1",
                resume_all=True,
            )

        # Both completed agents must be resumed
        assert "lead-1" in result["resumed_agents"], (
            "resume_team must include completed lead agent"
        )
        assert "worker-1" in result["resumed_agents"], (
            "resume_team must include completed worker agent"
        )
        assert len(result["resumed_agents"]) == 2

        # Both must be set to running
        db.update_agent.assert_any_call("lead-1", status="running")
        db.update_agent.assert_any_call("worker-1", status="running")


# ---------------------------------------------------------------------------
# Test 2: resume completed agent clears artifact_status
# ---------------------------------------------------------------------------

class TestResumeCompletedClearsArtifactStatus:
    """When resuming a completed agent, artifact_status must be set to None."""

    def test_resume_completed_clears_artifact_status(self, tmp_path):
        from phalanx.team.orchestrator import resume_single_agent

        agent = _make_agent(
            "worker-1",
            status="completed",
            artifact_status="success",
            chat_id="sess-abc",
        )

        db, pm, hm = _make_orchestrator_deps()
        db.get_agent.return_value = agent

        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        pm.spawn_resume.return_value = mock_proc

        with patch("phalanx.backends.get_backend") as mock_gb:
            mock_gb.return_value = MagicMock()

            result = resume_single_agent(
                phalanx_root=tmp_path,
                db=db,
                process_manager=pm,
                heartbeat_monitor=hm,
                agent_id="worker-1",
            )

        # artifact_status must be cleared
        db.update_agent.assert_any_call("worker-1", artifact_status=None)

        # Agent must transition to running
        db.update_agent.assert_any_call("worker-1", status="running")
        assert result["status"] == "running"


# ---------------------------------------------------------------------------
# Test 3: stop_team kills completing agents
# ---------------------------------------------------------------------------

class TestStopTeamKillsCompletingAgents:
    """stop_team() must kill agents in 'completing' status, not just
    'running', 'pending', and 'blocked_on_prompt'."""

    def test_stop_team_kills_completing_agents(self):
        from phalanx.team.orchestrator import stop_team

        completing_agent = _make_agent("worker-1", status="completing")
        db, pm, _ = _make_orchestrator_deps()
        db.list_agents.return_value = [completing_agent]

        with patch("phalanx.team.orchestrator._kill_team_monitor"):
            result = stop_team(db, pm, "team-1")

        # completing agent must be killed
        pm.kill_agent.assert_called_once_with("worker-1")

        # Agent status must be set to dead
        db.update_agent.assert_any_call("worker-1", status="dead")

        assert "worker-1" in result["stopped_agents"]


# ---------------------------------------------------------------------------
# Test 4: CLI shows "stopped" for completed agent
# ---------------------------------------------------------------------------

class TestCLIShowsStoppedForCompletedAgent:
    """The agent status CLI command must display 'stopped' (not 'completed')
    for agents whose DB status is 'completed'.

    The ADR specifies: completed -> stopped in user-visible output.
    Currently the CLI just dumps raw JSON, so this test verifies the
    display mapping exists."""

    def test_cli_agent_status_shows_stopped_for_completed(self, tmp_path):
        """agent status <id> must show 'stopped' not 'completed'."""
        from click.testing import CliRunner
        from phalanx.commands.agent import agent_group

        agent = _make_agent("worker-1", status="completed", artifact_status="success")

        runner = CliRunner()
        with patch("phalanx.commands.agent._get_root", return_value=tmp_path), \
             patch("phalanx.commands.agent._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.get_agent.return_value = agent
            mock_get_db.return_value = mock_db

            result = runner.invoke(agent_group, ["status", "worker-1"], obj={"root": str(tmp_path)})

        # The output must show "stopped" where the status would appear,
        # NOT the raw "completed" from the DB
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "stopped" in result.output, (
            f"CLI must display 'stopped' for completed agents, got: {result.output}"
        )
        assert '"completed"' not in result.output, (
            f"CLI must NOT display raw 'completed' status, got: {result.output}"
        )

    def test_cli_team_status_shows_stopped_for_completed(self, tmp_path):
        """team status <id> must show 'stopped' not 'completed' for agents."""
        from click.testing import CliRunner
        from phalanx.commands.team import team_group

        runner = CliRunner()

        team_status_data = {
            "team": {"id": "team-1", "status": "completed", "task": "test task"},
            "agents": [
                _make_agent("lead-1", status="completed", role="lead"),
                _make_agent("worker-1", status="completed"),
            ],
            "agent_count": 2,
            "running_count": 0,
            "costs": None,
        }

        with patch("phalanx.commands.team._get_root", return_value=tmp_path), \
             patch("phalanx.commands.team._get_db") as mock_get_db, \
             patch("phalanx.commands.team.get_team_status", create=True) as mock_gts:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            # Patch the import inside the function
            with patch("phalanx.team.orchestrator.get_team_status", return_value=team_status_data):
                mock_gts.return_value = team_status_data
                result = runner.invoke(
                    team_group,
                    ["status", "team-1"],
                    obj={"root": str(tmp_path)},
                )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        # Team status should show "stopped" not "completed"
        assert '"completed"' not in result.output, (
            f"CLI must map 'completed' to 'stopped' in display, got: {result.output}"
        )


# ---------------------------------------------------------------------------
# Test 5: resume_team accepts completed team status
# ---------------------------------------------------------------------------

class TestResumeTeamCompletedStatusAccepted:
    """resume_team() must work when the team itself has status='completed'.
    The team status must transition back to 'running'."""

    def test_resume_team_completed_status_accepted(self, tmp_path):
        from phalanx.team.orchestrator import resume_team

        lead = _make_agent("lead-1", status="completed", role="lead", chat_id="sess-lead")
        worker = _make_agent("worker-1", status="completed", role="worker", chat_id="sess-worker")

        db, pm, hm = _make_orchestrator_deps()
        db.list_agents.return_value = [lead, worker]
        db.get_team.return_value = {"id": "team-1", "status": "completed", "task": "test"}

        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        pm.spawn_resume.return_value = mock_proc

        with patch("phalanx.backends.get_backend") as mock_gb, \
             patch("phalanx.team.create._spawn_team_monitor"):
            mock_gb.return_value = MagicMock()

            # This must NOT raise — completed teams are resumable
            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=pm,
                heartbeat_monitor=hm,
                team_id="team-1",
                resume_all=True,
            )

        # Agents must be resumed
        assert len(result["resumed_agents"]) == 2, (
            f"Expected 2 resumed agents, got {result['resumed_agents']}"
        )

        # Team status must transition to running
        db.update_team_status.assert_called_with("team-1", "running")
