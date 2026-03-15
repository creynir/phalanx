"""Integration tests for Resume Context Building — IT-070 through IT-080."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phalanx.artifacts.schema import Artifact
from phalanx.artifacts.writer import write_artifact
from phalanx.db import StateDB
from phalanx.team.orchestrator import (
    _build_resume_prompt,
    resume_single_agent,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


@pytest.fixture
def team_setup(db, tmp_path):
    """Set up a team with lead and 2 workers, each with artifacts."""
    db.create_team("t1", "build a calculator")
    db.create_agent("lead-t1", "t1", "coordinate", role="lead")
    db.create_agent("w1", "t1", "write code", role="worker")
    db.create_agent("w2", "t1", "write tests", role="worker")

    for aid, status, output in [
        ("w1", "success", {"files": ["calc.py"]}),
        ("w2", "success", {"files": ["test_calc.py"]}),
    ]:
        db.update_agent(aid, status="suspended", artifact_status=status)
        art = Artifact(status=status, output=output, agent_id=aid, team_id="t1")
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / aid
        write_artifact(artifact_dir, art)

    db.update_agent("lead-t1", status="suspended")

    # Create soul files so _build_resume_prompt works
    Path(__file__).parent.parent.parent / "phalanx" / "soul"
    return db, tmp_path


class TestIT070_LeadContextIntegration:
    """IT-070: Compiles previous worker artifacts into lead resume."""

    def test_lead_resume_has_worker_artifacts(self, team_setup):
        db, root = team_setup
        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "w1" in prompt
        assert "w2" in prompt
        assert "calc.py" in prompt


class TestIT071_LeadTaskPrevention:
    """IT-071: Lead resume instructs NOT to resend tasks to completed workers."""

    def test_no_repeat_instruction(self, team_setup):
        db, root = team_setup
        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert (
            "Do NOT" in prompt
            or "not resume workers" in prompt.lower()
            or "already have successful" in prompt
        )


class TestIT072_WorkerWaitInstruction:
    """IT-072: Completed worker resume appends 'Wait for new assignment'."""

    def test_completed_worker_waits(self, team_setup):
        db, root = team_setup
        agent = db.get_agent("w1")
        prompt = _build_resume_prompt(root, db, agent)
        assert (
            "Do NOT redo" in prompt
            or "Wait for" in prompt.lower()
            or "new assignment" in prompt.lower()
        )


class TestIT073_WorkerIncomplete:
    """IT-073: Resuming worker without artifacts reloads original task."""

    def test_incomplete_worker_gets_original_task(self, db, tmp_path):
        db.create_team("t2", "task")
        db.create_agent("w3", "t2", "write integration tests", role="worker")
        db.update_agent("w3", status="dead")

        agent = db.get_agent("w3")
        prompt = _build_resume_prompt(tmp_path, db, agent)
        assert "did not complete" in prompt.lower() or "write integration tests" in prompt


class TestIT074_LeadPendingMessages:
    """IT-074: Resumed lead context includes pending unread feed messages."""

    def test_pending_messages_in_resume(self, team_setup):
        db, root = team_setup
        msg_dir = root / "teams" / "t1" / "messages"
        msg_dir.mkdir(parents=True, exist_ok=True)
        (msg_dir / "msg_lead-t1_001.txt").write_text("New priority: add tests")

        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "New priority: add tests" in prompt


class TestIT075_LivelockPrevention:
    """IT-075: Monitor avoids infinitely resuming workers with successful artifacts."""

    def test_resume_prevention_instruction(self, team_setup):
        db, root = team_setup
        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "already have successful artifacts" in prompt or "Do NOT resume" in prompt


class TestIT076_ResumeSuspendedAgent:
    """IT-076: resume-agent successfully triggers process rebirth."""

    def test_resume_suspended(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code", role="worker")
        db.update_agent("w1", status="suspended")

        mock_pm = MagicMock()
        mock_hb = MagicMock()
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with patch("phalanx.backends.get_backend") as mock_gb:
            mock_gb.return_value = MagicMock()
            result = resume_single_agent(tmp_path, db, mock_pm, mock_hb, "w1")
            assert result["status"] == "running"
            assert db.get_agent("w1")["status"] == "running"


class TestIT077_ResumeRunningAgent:
    """IT-077: Resume aborted safely when process already active."""

    def test_resume_running_errors(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code", role="worker")
        db.update_agent("w1", status="running")

        mock_pm = MagicMock()
        mock_hb = MagicMock()

        with pytest.raises(ValueError, match="running"):
            resume_single_agent(tmp_path, db, mock_pm, mock_hb, "w1")


class TestIT078_AutoApproveResumption:
    """IT-078: Re-injects --yolo/auto-approve flags during resume."""

    def test_auto_approve_passed(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code", role="worker", backend="cursor")
        db.update_agent("w1", status="dead")

        mock_pm = MagicMock()
        mock_hb = MagicMock()
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with patch("phalanx.backends.get_backend") as mock_gb:
            mock_backend = MagicMock()
            mock_gb.return_value = mock_backend
            resume_single_agent(tmp_path, db, mock_pm, mock_hb, "w1", auto_approve=True)
            spawn_call = mock_pm.spawn.call_args
            assert (
                spawn_call.kwargs.get("auto_approve") is True
                or spawn_call[1].get("auto_approve") is True
            )


class TestIT079_RediscoveryLog:
    """IT-079: Monitor finds a freshly resumed tmux session."""

    def test_rediscovery(self):
        from phalanx.monitor.team_monitor import run_team_monitor

        mock_pm = MagicMock()
        mock_pm.get_process.return_value = None
        mock_pm.consume_startup_blocked.return_value = None
        mock_proc = MagicMock()
        mock_proc.stream_log = Path("/tmp/stream.log")
        mock_pm.discover_agent.return_value = mock_proc

        mock_db = MagicMock()
        mock_db.list_agents.return_value = [
            {"id": "w1", "status": "running", "role": "worker", "artifact_status": None}
        ]

        mock_hb = MagicMock()
        mock_hb.get_state.return_value = None
        mock_sd = MagicMock()
        mock_sd.check_agent.return_value = None

        # We'll just verify discover_agent is called
        mock_hb_state = MagicMock()
        mock_hb_state.last_heartbeat = 0
        mock_hb.check.return_value = mock_hb_state

        mock_db.get_agent.return_value = {"artifact_status": None}

        # Make the loop exit after first iteration
        mock_db.list_agents.side_effect = [
            [{"id": "w1", "status": "running", "role": "worker", "artifact_status": None}],
            [],  # Empty on second call to exit loop
        ]

        run_team_monitor(
            "t1", mock_db, mock_pm, mock_hb, mock_sd, poll_interval=0, lead_agent_id="lead-1"
        )
        mock_pm.discover_agent.assert_called()


class TestIT080_ResumeAfterEscalation:
    """IT-080: Worker with escalation artifact resumed after Outer Loop intervention."""

    def test_escalation_resume_context(self, db, tmp_path):
        db.create_team("t3", "test task")
        db.create_agent("w5", "t3", "deploy to prod", role="worker")
        db.update_agent("w5", status="suspended", artifact_status="escalation")

        art = Artifact(
            status="escalation",
            output={"error": "cannot deploy — needs infra change"},
            agent_id="w5",
            team_id="t3",
        )
        art_dir = tmp_path / "teams" / "t3" / "agents" / "w5"
        write_artifact(art_dir, art)

        db.post_to_feed("t3", "engineering_manager", "Infra resolved. Resume deployment.")

        from phalanx.monitor.team_monitor import _should_wake_suspended

        agent = db.get_agent("w5")
        assert _should_wake_suspended(db, agent) is True
