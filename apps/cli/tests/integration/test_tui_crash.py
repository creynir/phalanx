"""Integration tests for TUI Rendering Crash Recovery — IT-046 through IT-051."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phalanx.monitor.stall import _check_process_exited
from phalanx.process.manager import AgentProcess


pytestmark = pytest.mark.integration


class TestIT046_EscalationRequiredCrash:
    """IT-046: Injecting escalation_required crashes TUI; stall detector catches it."""

    def test_process_exited_after_crash(self):
        lines = [
            "zsh: command not found: node",
            "zsh: parse error",
            "user@host$ ",
        ]
        assert _check_process_exited(lines) is True


# IT-047: moved to tests/future_backlog/test_integration_backlog.py


class TestIT048_TUICrashGhostAutoRestart:
    """IT-048: Node process crash → ghost session → auto-restart chain."""

    def test_full_chain(self):
        from phalanx.monitor.team_monitor import _auto_restart_agent

        mock_pm = MagicMock()
        mock_pm._root = "/tmp"
        mock_db = MagicMock()
        mock_hb = MagicMock()

        with patch("phalanx.team.orchestrator.resume_single_agent") as mock_resume:
            _auto_restart_agent(mock_pm, mock_db, mock_hb, "t1", "w1", "lead1", None)
            mock_pm.kill_agent.assert_called_once_with("w1")
            mock_db.update_agent.assert_called_once_with("w1", status="dead")
            mock_resume.assert_called_once()


# IT-049, IT-050: moved to tests/future_backlog/test_integration_backlog.py


class TestIT051_LivenessAfterTUICrash:
    """IT-051: After node process crash, is_alive() returns False."""

    def test_is_alive_false_for_all_shells(self):
        shells = ["zsh", "bash", "sh", "fish", "dash"]
        for shell in shells:
            proc = AgentProcess(
                agent_id="a1",
                team_id="t1",
                session_name="s1",
                stream_log=Path("/tmp/s.log"),
                backend=MagicMock(),
            )
            mock_pane = MagicMock()
            mock_pane.pane_current_command = shell
            mock_session = MagicMock()
            mock_session.active_window.active_pane = mock_pane

            with patch("phalanx.process.manager.libtmux") as mock_libtmux:
                mock_server = MagicMock()
                mock_server.sessions.get.return_value = mock_session
                mock_libtmux.Server.return_value = mock_server
                assert proc.is_alive() is False, f"Expected False for shell: {shell}"
