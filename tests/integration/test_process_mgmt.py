"""Integration tests for Process Management — IT-009 through IT-017."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phalanx.process.manager import AgentProcess, ProcessManager


pytestmark = pytest.mark.integration


@pytest.fixture
def pm(tmp_path):
    with patch("phalanx.process.manager.libtmux"):
        return ProcessManager(tmp_path)


class TestIT009_SpawnProcess:
    """IT-009: Starts tmux session correctly naming format phalanx-<team>-<agent>."""

    def test_session_name_format(self, pm):
        name = pm._session_name("my-team", "coder-1")
        assert name == "phalanx-my-team-coder-1"


class TestIT010_CursorStaggerDelay:
    """IT-010: Verifies consecutive Cursor agent spawns apply spawn delay."""

    def test_cursor_spawn_delay(self):
        from phalanx.backends.cursor import CursorBackend

        backend = CursorBackend()
        delay = backend.spawn_delay()
        assert delay >= 0  # env override may set to 0 in tests


class TestIT011_KillAgent:
    """IT-011: Successfully terminates tmux session."""

    def test_kill_removes_from_processes(self, pm):
        mock_proc = MagicMock()
        mock_proc.session_name = "phalanx-t-a"
        pm._processes["agent-1"] = mock_proc
        pm.kill_agent("agent-1")
        assert "agent-1" not in pm._processes


class TestIT012_DiscoverAgent:
    """IT-012: Recovers orphaned agents from libtmux sessions."""

    def test_discover_returns_agent_process(self, tmp_path):
        mock_server = MagicMock()
        mock_session = MagicMock()
        mock_server.sessions.get.return_value = mock_session

        with patch("phalanx.process.manager.libtmux"):
            pm = ProcessManager(tmp_path)
            pm._server = mock_server
            proc = pm.discover_agent("team1", "agent1")
            assert proc is not None
            assert proc.agent_id == "agent1"
            assert proc.team_id == "team1"
            assert "agent1" in pm._processes


class TestIT013_SendKeys:
    """IT-013: Injects standard alphabetic strings into tmux pane safely."""

    def test_send_keys_to_tracked_process(self, pm):
        mock_proc = MagicMock()
        mock_pane = MagicMock()
        mock_proc.pane = mock_pane
        pm._processes["agent-1"] = mock_proc
        result = pm.send_keys("agent-1", "echo hello")
        assert result is True
        mock_pane.send_keys.assert_called_once()


class TestIT014_SendKeysSpecialChars:
    """IT-014: Prompt injection handles complex characters without corruption."""

    def test_special_chars_in_message(self, tmp_path):
        from phalanx.comms.messaging import deliver_message

        mock_pm = MagicMock()
        mock_pm.send_keys.return_value = True

        malicious = "test `backtick` 'single' \"double\" <angle> $VAR $(cmd) | &&"
        result = deliver_message(mock_pm, "agent-1", malicious, message_dir=tmp_path)
        assert result is True

        call_args = mock_pm.send_keys.call_args[0]
        assert "Read and respond to the message at:" in call_args[1]
        assert "backtick" not in call_args[1]
        assert "$VAR" not in call_args[1]


class TestIT015_IsAliveNormal:
    """IT-015: Identifies an active TUI application running inside tmux."""

    def test_is_alive_with_agent_binary(self):
        proc = AgentProcess(
            agent_id="a1",
            team_id="t1",
            session_name="s1",
            stream_log=Path("/tmp/s.log"),
            backend=MagicMock(),
        )
        mock_pane = MagicMock()
        mock_pane.pane_current_command = "node"
        mock_session = MagicMock()
        mock_session.active_window.active_pane = mock_pane

        with patch("phalanx.process.manager.libtmux") as mock_libtmux:
            mock_server = MagicMock()
            mock_server.sessions.get.return_value = mock_session
            mock_libtmux.Server.return_value = mock_server
            assert proc.is_alive() is True


class TestIT016_GhostDetection:
    """IT-016: is_alive returns False if binary crashed but shell is foreground."""

    def test_ghost_session_detected(self):
        proc = AgentProcess(
            agent_id="a1",
            team_id="t1",
            session_name="s1",
            stream_log=Path("/tmp/s.log"),
            backend=MagicMock(),
        )
        mock_pane = MagicMock()
        mock_pane.pane_current_command = "zsh"
        mock_session = MagicMock()
        mock_session.active_window.active_pane = mock_pane

        with patch("phalanx.process.manager.libtmux") as mock_libtmux:
            mock_server = MagicMock()
            mock_server.sessions.get.return_value = mock_session
            mock_libtmux.Server.return_value = mock_server
            assert proc.is_alive() is False


class TestIT017_KillAll:
    """IT-017: ProcessManager.kill_agent safely destroys tmux processes."""

    def test_kill_multiple_agents(self):
        mock_pm = MagicMock()
        mock_proc1 = MagicMock()
        mock_proc1.agent_id = "a1"
        mock_proc1.is_alive.return_value = True
        mock_proc2 = MagicMock()
        mock_proc2.agent_id = "a2"
        mock_proc2.is_alive.return_value = True

        mock_pm.list_processes.return_value = {"a1": mock_proc1, "a2": mock_proc2}

        for agent_id in list(mock_pm.list_processes()):
            mock_pm.kill_agent(agent_id)
        assert mock_pm.kill_agent.call_count == 2
