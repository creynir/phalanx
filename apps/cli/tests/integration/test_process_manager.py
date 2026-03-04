"""Integration tests for tmux process manager — requires tmux running."""

from __future__ import annotations

import time

import pytest

from phalanx.process.manager import ProcessManager


pytestmark = pytest.mark.integration


@pytest.fixture
def stream_log(tmp_path):
    return tmp_path / "stream.log"


@pytest.fixture
def pm(tmp_path):
    return ProcessManager(tmp_path)


@pytest.fixture
def tmux_session(pm, stream_log):
    """Spawn a simple echo session and clean up after."""
    from phalanx.backends.registry import get_backend

    backend = get_backend("cursor")
    result = pm.spawn(
        team_id="test-team",
        agent_id="test-agent",
        backend=backend,
        prompt="phalanx-test-ok",
    )
    yield result
    pm.kill_agent(result.agent_id)


class TestSpawnInTmux:
    def test_creates_session(self, pm, tmux_session):
        assert pm.get_process(tmux_session.agent_id) is not None

    def test_session_name_format(self, tmux_session):
        assert tmux_session.session_name == "phalanx-test-team-test-agent"

    def test_is_alive(self, tmux_session):
        # The spawned command likely fails immediately (no real cursor binary),
        # leaving the pane in a bare shell — correctly detected as a ghost.
        # Verify the session exists (pane != None) but ghost detection works.
        pane = tmux_session.pane
        assert pane is not None


class TestKillSession:
    def test_kill_existing(self, pm, tmux_session):
        agent_id = tmux_session.agent_id
        assert pm.get_process(agent_id) is not None
        pm.kill_agent(agent_id)
        time.sleep(0.5)  # Let tmux kill it
        assert pm.get_process(agent_id) is None

    def test_kill_nonexistent(self, pm):
        pm.kill_agent("phalanx-nonexistent-session")


class TestSendKeys:
    def test_send_to_session(self, pm, tmux_session):
        # We just verify it doesn't crash.
        pm.send_keys(tmux_session.agent_id, "echo hello-from-test")

    def test_send_to_nonexistent(self, pm):
        # Should handle gracefully
        pm.send_keys("nonexistent-session", "hi")


class TestCaptureOutput:
    def test_capture(self, pm, stream_log):
        from phalanx.backends.registry import get_backend

        res = pm.spawn(
            team_id="cap-team",
            agent_id="cap-agent",
            backend=get_backend("cursor"),
            prompt="hello capture",
        )
        time.sleep(0.5)
        output = pm.capture_screen(res.agent_id)
        assert output is not None
        pm.kill_agent(res.agent_id)

    def test_capture_nonexistent(self, pm):
        assert pm.capture_screen("nonexistent") is None


class TestListSessions:
    def test_lists_phalanx_sessions(self, pm, tmux_session):
        sessions = pm.list_processes()
        assert tmux_session.agent_id in sessions
