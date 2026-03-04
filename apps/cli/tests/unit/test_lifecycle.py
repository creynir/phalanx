"""Tests for agent lifecycle state machine."""

from __future__ import annotations

from unittest.mock import patch, MagicMock


from phalanx.monitor.lifecycle import run_monitor_loop
from phalanx.monitor.stall import AgentState, StallEvent


class TestRunMonitorLoop:
    def test_exceeds_max_runtime(self):
        pm = MagicMock()
        hm = MagicMock()
        sd = MagicMock()

        # Use a list of times to return, to simulate elapsed time without breaking logging
        _times = [1000.0, 3000.0, 3000.0, 3000.0, 3000.0]

        def mock_time():
            if _times:
                return _times.pop(0)
            return 3000.0

        with patch("time.time", side_effect=mock_time):
            result = run_monitor_loop("a1", pm, hm, sd, max_runtime=1800, poll_interval=0)

        assert result.final_state == "failed"
        pm.kill_agent.assert_called_once_with("a1")

    @patch("time.sleep", return_value=None)
    def test_agent_dead(self, mock_sleep):
        pm = MagicMock()
        hm = MagicMock()
        sd = MagicMock()
        sd.check_agent.return_value = StallEvent(state=AgentState.DEAD, agent_id="a1")

        result = run_monitor_loop("a1", pm, hm, sd, max_runtime=1800, poll_interval=0)
        assert result.final_state == "dead"

    @patch("time.sleep", return_value=None)
    def test_agent_idle_timeout(self, mock_sleep):
        pm = MagicMock()
        hm = MagicMock()
        sd = MagicMock()
        sd.check_agent.return_value = StallEvent(state=AgentState.IDLE_TIMEOUT, agent_id="a1")

        result = run_monitor_loop("a1", pm, hm, sd, max_runtime=1800, poll_interval=0)
        assert result.final_state == "suspended"
        pm.kill_agent.assert_called_once_with("a1")

    @patch("time.sleep", return_value=None)
    def test_agent_blocked_on_prompt(self, mock_sleep):
        pm = MagicMock()
        hm = MagicMock()
        sd = MagicMock()
        sd.check_agent.return_value = StallEvent(
            state=AgentState.BLOCKED_ON_PROMPT,
            agent_id="a1",
            prompt_type="workspace_trust",
            screen_text="Trust this workspace?",
        )

        result = run_monitor_loop("a1", pm, hm, sd, max_runtime=1800, poll_interval=0)
        assert result.final_state == "blocked_on_prompt"
        assert result.prompt_type == "workspace_trust"

    @patch("time.sleep", return_value=None)
    def test_agent_stalled_max_retries(self, mock_sleep):
        pm = MagicMock()
        hm = MagicMock()
        sd = MagicMock()
        sd.check_agent.return_value = StallEvent(state=AgentState.STALLED, agent_id="a1")
        sd.get_retry_delay.return_value = 0

        result = run_monitor_loop(
            "a1", pm, hm, sd, max_runtime=1800, poll_interval=0, max_retries=2
        )
        assert result.final_state == "failed"
        assert result.retry_count == 3
        pm.kill_agent.assert_called_once_with("a1")
