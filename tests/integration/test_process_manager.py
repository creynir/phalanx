"""Integration tests for tmux process manager — requires tmux running."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from phalanx.process.manager import (
    spawn_in_tmux,
    kill_session,
    session_exists,
    send_keys_to_session,
    capture_pane_output,
    list_phalanx_sessions,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def stream_log(tmp_path):
    return tmp_path / "stream.log"


@pytest.fixture
def tmux_session(stream_log):
    """Spawn a simple echo session and clean up after."""
    result = spawn_in_tmux(
        cmd=["echo", "phalanx-test-ok"],
        team_id="test-team",
        agent_id="test-agent",
        stream_log=stream_log,
    )
    yield result
    kill_session(result["session_name"])


class TestSpawnInTmux:
    def test_creates_session(self, tmux_session):
        assert session_exists(tmux_session["session_name"])

    def test_session_name_format(self, tmux_session):
        assert tmux_session["session_name"] == "phalanx-test-team-test-agent"

    def test_pane_pid(self, tmux_session):
        assert tmux_session["pane_pid"] is not None


class TestKillSession:
    def test_kill_existing(self, tmux_session):
        name = tmux_session["session_name"]
        assert kill_session(name) is True
        assert session_exists(name) is False

    def test_kill_nonexistent(self):
        assert kill_session("phalanx-nonexistent-session") is False


class TestSendKeys:
    def test_send_to_session(self, tmux_session):
        name = tmux_session["session_name"]
        result = send_keys_to_session(name, "echo hello-from-test")
        assert result is True

    def test_send_to_nonexistent(self):
        assert send_keys_to_session("nonexistent-session", "hi") is False


class TestCaptureOutput:
    def test_capture(self, tmux_session):
        name = tmux_session["session_name"]
        time.sleep(0.5)
        output = capture_pane_output(name)
        assert output is not None

    def test_capture_nonexistent(self):
        assert capture_pane_output("nonexistent") is None


class TestListSessions:
    def test_lists_phalanx_sessions(self, tmux_session):
        sessions = list_phalanx_sessions()
        assert tmux_session["session_name"] in sessions
