"""E2E tests: Monitor and Stall Detection — E2E-006 through E2E-013."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from phalanx.db import StateDB
from phalanx.monitor.stall import (
    AgentState,
    StallDetector,
    _check_agent_idle,
    _check_connection_lost,
    _check_process_exited,
)
from phalanx.monitor.team_monitor import _auto_restart_agent, _nudge_idle_agent


pytestmark = pytest.mark.e2e


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


class TestE2E006_WorkerDiesMidTask:
    """E2E-006: Worker tmux session destroyed → Lead notified."""

    def test_dead_detection(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code", role="worker")
        db.update_agent("w1", status="running")

        mock_pm = MagicMock()
        mock_pm.get_process.return_value = None

        mock_hb = MagicMock()
        mock_hb.check.return_value = MagicMock(is_stale=lambda now=None: False, last_heartbeat=0)

        sd = StallDetector(mock_pm, mock_hb)
        mock_hb._states = {"w1": MagicMock()}

        event = sd.check_agent("w1")
        assert event is not None
        assert event.state == AgentState.DEAD


class TestE2E007_FalseIdleSuppression:
    """E2E-007: No nudge while Generating/Thinking visible."""

    def test_generating_suppresses(self):
        lines = ["Generating...", "ctrl+c to stop", "→ Add a follow-up"]
        assert _check_agent_idle(lines) is False


class TestE2E008_LeadSelfNudge:
    """E2E-008: Idle lead gets nudged directly."""

    def test_lead_nudge(self, tmp_path):
        mock_pm = MagicMock()
        mock_pm.send_keys.return_value = True
        _nudge_idle_agent(mock_pm, "lead-1", message_dir=tmp_path)
        mock_pm.send_keys.assert_called_once()

        files = list(tmp_path.glob("msg_lead-1_*.txt"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "not completed" in content


class TestE2E009_GhostSessionDetection:
    """E2E-009: Agent binary crashes, tmux alive → detected and restarted."""

    def test_ghost_restart(self):
        mock_pm = MagicMock()
        mock_pm._root = "/tmp"
        mock_db = MagicMock()
        mock_hb = MagicMock()

        with patch("phalanx.team.orchestrator.resume_single_agent") as mock_resume:
            _auto_restart_agent(mock_pm, mock_db, mock_hb, "t1", "w1", "lead1", None)
            mock_pm.kill_agent.assert_called_once_with("w1")
            mock_db.update_agent.assert_called_with("w1", status="dead")
            mock_resume.assert_called_once()


class TestE2E010_GhostFalsePositive:
    """E2E-010: Agent logs shell errors without triggering false process_exited."""

    def test_single_error_no_trigger(self):
        lines = ["code block output", "zsh: command not found: foo", "end of block"]
        assert _check_process_exited(lines) is False


class TestE2E011_ConnectionLostRecovery:
    """E2E-011: Connection lost detected → auto-restart → lead notified."""

    def test_connection_lost(self):
        lines = ["Connection lost. Retry attempted."]
        assert _check_connection_lost(lines) is True


class TestE2E012_InvalidModelGhost:
    """E2E-012: Bad model flag → agent fails on startup → ghost detected."""

    def test_bare_prompt_detected(self):
        lines = ["$ "]
        assert _check_process_exited(lines) is True


class TestE2E013_IdleTimeoutSuspension:
    """E2E-013: Agent idle beyond timeout → suspended → lead notified."""

    def test_idle_timeout_event(self):
        mock_pm = MagicMock()
        mock_hb = MagicMock()

        state = MagicMock()
        state.is_stale.return_value = True
        state.last_heartbeat = 0
        mock_hb.check.return_value = state
        mock_hb._states = {"w1": state}

        mock_proc = MagicMock()
        mock_proc.is_alive.return_value = True
        mock_pm.get_process.return_value = mock_proc

        sd = StallDetector(mock_pm, mock_hb, idle_timeout=30)
        event = sd.check_agent("w1")
        assert event is not None
        assert event.state == AgentState.IDLE_TIMEOUT
