"""Tests for stall detection and TUI screen scraping."""

from __future__ import annotations

from unittest.mock import MagicMock


from phalanx.monitor.stall import (
    StallDetector,
    AgentState,
    _check_workspace_trust,
    _check_permission_prompt,
    _check_tool_approval,
    _check_error_prompt,
    _check_agent_idle,
)


class TestPromptPatterns:
    def test_workspace_trust(self):
        assert _check_workspace_trust(["Workspace Trust", "Do you trust this?"])
        assert _check_workspace_trust(["Trust this workspace", "Press [y] to accept"])
        assert not _check_workspace_trust(["Just some normal text"])

    def test_permission_prompt(self):
        assert _check_permission_prompt(["Allow", "this operation?"])
        assert _check_permission_prompt(["[y/N]"])
        assert not _check_permission_prompt(["Proceeding with operation..."])

    def test_tool_approval(self):
        assert _check_tool_approval(["Run python test.py ? ["])
        assert _check_tool_approval(["Execute bash ? [y/N]"])
        assert not _check_tool_approval(["Running python test.py"])

    def test_error_prompt(self):
        assert _check_error_prompt(["retry [R]"])
        assert _check_error_prompt(["abort (A)"])
        assert not _check_error_prompt(["Operation failed."])

    def test_agent_idle(self):
        assert _check_agent_idle(["❯"])
        assert _check_agent_idle(["? for shortcuts"])
        assert not _check_agent_idle(["Working..."])


class TestStallDetector:
    def test_check_agent_dead(self):
        pm = MagicMock()
        hm = MagicMock()
        pm.get_process.return_value = None
        hm.check.return_value = MagicMock()

        sd = StallDetector(pm, hm)
        # Startup grace period skips the first few checks within 60s.
        # Simulate enough consecutive dead checks to exceed the threshold.
        from phalanx.monitor.stall import STARTUP_DEAD_THRESHOLD

        for _ in range(STARTUP_DEAD_THRESHOLD - 1):
            assert sd.check_agent("a1") is None
        event = sd.check_agent("a1")
        assert event is not None
        assert event.state == AgentState.DEAD

    def test_check_agent_idle_timeout(self):
        pm = MagicMock()
        hm = MagicMock()
        hb_state = MagicMock()
        hb_state.is_stale.return_value = True
        hm.check.return_value = hb_state
        pm.get_process.return_value.is_alive.return_value = True

        sd = StallDetector(pm, hm)
        event = sd.check_agent("a1")
        assert event is not None
        assert event.state == AgentState.IDLE_TIMEOUT

    def test_check_agent_blocked_on_prompt(self):
        pm = MagicMock()
        hm = MagicMock()
        hb_state = MagicMock()
        hb_state.is_stale.return_value = False
        hm.check.return_value = hb_state
        pm.get_process.return_value.is_alive.return_value = True
        pm.capture_screen.return_value = ["Allow this operation?"]

        sd = StallDetector(pm, hm, check_interval=0)

        event = sd.check_agent("a1")
        assert event is not None
        assert event.state == AgentState.BLOCKED_ON_PROMPT
        assert event.prompt_type == "permission_prompt"

    def test_retry_backoff(self):
        sd = StallDetector(MagicMock(), MagicMock())
        assert sd.get_retry_delay("a1") == 5
        sd.record_retry("a1")
        assert sd.get_retry_delay("a1") == 10
        sd.record_retry("a1")
        assert sd.get_retry_delay("a1") == 20
        sd.reset_retries("a1")
        assert sd.get_retry_delay("a1") == 5
