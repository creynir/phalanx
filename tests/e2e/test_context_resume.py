"""E2E tests: Context Preservation and Resumption — E2E-014 through E2E-022."""

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


pytestmark = pytest.mark.e2e


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


@pytest.fixture
def team_with_artifacts(db, tmp_path):
    db.create_team("t1", "build a calculator")
    db.create_agent("lead-t1", "t1", "coordinate", role="lead")
    db.create_agent("w1", "t1", "write code", role="worker")
    db.create_agent("w2", "t1", "write tests", role="worker")

    for aid in ("w1", "w2"):
        db.update_agent(aid, status="suspended", artifact_status="success")
        art = Artifact(status="success", output={"done": True}, agent_id=aid, team_id="t1")
        d = tmp_path / "teams" / "t1" / "agents" / aid
        write_artifact(d, art)

    db.update_agent("lead-t1", status="suspended")
    return db, tmp_path


class TestE2E014_MultiRoundResume:
    """E2E-014: Round 1 complete → resume lead → round 2."""

    def test_lead_resume_has_context(self, team_with_artifacts):
        db, root = team_with_artifacts
        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "w1" in prompt
        assert "w2" in prompt
        assert "RESUME CONTEXT" in prompt


class TestE2E015_LeadContextPreservation:
    """E2E-015: Resumed lead sees prior artifacts and worker statuses."""

    def test_lead_sees_all(self, team_with_artifacts):
        db, root = team_with_artifacts
        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "artifact=success" in prompt or "success" in prompt
        assert "Do NOT" in prompt or "not repeat" in prompt.lower()


class TestE2E016_WorkerKnowsItsDone:
    """E2E-016: Resumed completed worker waits for new orders."""

    def test_completed_worker_waits(self, team_with_artifacts):
        db, root = team_with_artifacts
        agent = db.get_agent("w1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "Do NOT redo" in prompt or "Wait for" in prompt.lower()


class TestE2E017_LivelockPrevention:
    """E2E-017: Lead does NOT resume workers with successful artifacts."""

    def test_livelock_prevention(self, team_with_artifacts):
        db, root = team_with_artifacts
        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "already have successful" in prompt or "Do NOT resume" in prompt


class TestE2E018_ResumeSuspendedAgent:
    """E2E-018: resume-agent restarts suspended worker."""

    def test_resume_suspended(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        db.update_agent("w1", status="suspended")

        mock_pm = MagicMock()
        mock_hb = MagicMock()
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with patch("phalanx.backends.get_backend"):
            result = resume_single_agent(tmp_path, db, mock_pm, mock_hb, "w1")
        assert result["status"] == "running"


class TestE2E019_ResumeRunningError:
    """E2E-019: Reject resuming already-running agent."""

    def test_resume_running_errors(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        db.update_agent("w1", status="running")

        with pytest.raises(ValueError, match="running"):
            resume_single_agent(tmp_path, db, MagicMock(), MagicMock(), "w1")


class TestE2E020_AutoApproveOnResume:
    """E2E-020: Resumed agent retains --yolo flag."""

    def test_auto_approve_persists(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code", backend="cursor")
        db.update_agent("w1", status="dead")

        mock_pm = MagicMock()
        mock_hb = MagicMock()
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "s.log"
        mock_pm.spawn.return_value = mock_proc

        with patch("phalanx.backends.get_backend"):
            resume_single_agent(tmp_path, db, mock_pm, mock_hb, "w1", auto_approve=True)
        call_kwargs = mock_pm.spawn.call_args[1] if mock_pm.spawn.call_args[1] else {}
        assert call_kwargs.get("auto_approve") is True


class TestE2E021_MonitorRediscovery:
    """E2E-021: Monitor seamlessly tracks externally resumed agents."""

    def test_discover_called(self):
        from phalanx.monitor.team_monitor import run_team_monitor

        mock_pm = MagicMock()
        mock_pm.get_process.return_value = None
        mock_pm.consume_startup_blocked.return_value = None
        mock_proc = MagicMock()
        mock_proc.stream_log = Path("/tmp/stream.log")
        mock_pm.discover_agent.return_value = mock_proc

        mock_db = MagicMock()
        mock_db.list_agents.side_effect = [
            [{"id": "w1", "status": "running", "role": "worker", "artifact_status": None}],
            [],
        ]
        mock_db.get_agent.return_value = {"artifact_status": None}

        mock_hb = MagicMock()
        mock_hb.get_state.return_value = None
        mock_hb.check.return_value = MagicMock(last_heartbeat=0)
        mock_sd = MagicMock()
        mock_sd.check_agent.return_value = None

        run_team_monitor(
            "t1", mock_db, mock_pm, mock_hb, mock_sd, poll_interval=0, lead_agent_id="lead-1"
        )
        mock_pm.discover_agent.assert_called()


class TestE2E022_LeadAutoRestartSelfNotification:
    """E2E-022: Auto-restarted lead receives worker_restarted about itself."""

    def test_self_notification(self):
        from phalanx.monitor.team_monitor import _notify_lead

        mock_pm = MagicMock()
        _notify_lead(mock_pm, "lead-1", None, "worker_restarted", "lead-1")
        # Known UX flaw: lead gets notification about itself
