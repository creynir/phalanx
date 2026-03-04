"""Integration tests for monitor/lifecycle.py — DEM-style single-agent monitoring loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from phalanx.monitor.lifecycle import MonitorResult, run_monitor_loop
from phalanx.monitor.stall import AgentState, StallEvent


pytestmark = pytest.mark.integration


@pytest.fixture
def pm():
    return MagicMock()


@pytest.fixture
def hb():
    return MagicMock()


@pytest.fixture
def sd():
    m = MagicMock()
    m.get_retry_delay.return_value = 0
    return m


class TestMonitorLoopDead:
    """Agent dies on first check."""

    def test_returns_dead(self, pm, hb, sd):
        sd.check_agent.return_value = StallEvent(
            agent_id="w1", state=AgentState.DEAD, screen_text="$ ", prompt_type=""
        )
        result = run_monitor_loop(
            "w1",
            pm,
            hb,
            sd,
            max_retries=3,
            max_runtime=9999,
            poll_interval=0,
        )
        assert result.final_state == "dead"
        assert isinstance(result, MonitorResult)


class TestMonitorLoopIdleTimeout:
    """Agent hits idle timeout."""

    def test_returns_suspended(self, pm, hb, sd):
        sd.check_agent.return_value = StallEvent(
            agent_id="w1", state=AgentState.IDLE_TIMEOUT, screen_text="", prompt_type=""
        )
        result = run_monitor_loop(
            "w1",
            pm,
            hb,
            sd,
            max_retries=3,
            max_runtime=9999,
            poll_interval=0,
        )
        assert result.final_state == "suspended"
        pm.kill_agent.assert_called_once_with("w1")


class TestMonitorLoopBlockedNoCallback:
    """Agent blocked on prompt without callback."""

    def test_returns_blocked(self, pm, hb, sd):
        sd.check_agent.return_value = StallEvent(
            agent_id="w1",
            state=AgentState.BLOCKED_ON_PROMPT,
            screen_text="Trust workspace?",
            prompt_type="workspace_trust",
        )
        result = run_monitor_loop(
            "w1",
            pm,
            hb,
            sd,
            max_retries=3,
            max_runtime=9999,
            poll_interval=0,
        )
        assert result.final_state == "blocked_on_prompt"
        assert result.prompt_type == "workspace_trust"


class TestMonitorLoopBlockedWithCallback:
    """Agent blocked on prompt, callback returns False to stop."""

    def test_callback_stops(self, pm, hb, sd):
        sd.check_agent.return_value = StallEvent(
            agent_id="w1",
            state=AgentState.BLOCKED_ON_PROMPT,
            screen_text="Permission?",
            prompt_type="permission_prompt",
        )
        result = run_monitor_loop(
            "w1",
            pm,
            hb,
            sd,
            max_retries=3,
            max_runtime=9999,
            poll_interval=0,
            on_blocked=lambda aid, ev: False,
        )
        assert result.final_state == "blocked_on_prompt"


class TestMonitorLoopStallExhausted:
    """Agent stalls repeatedly, exhausts retries."""

    def test_returns_failed(self, pm, hb, sd):
        sd.check_agent.return_value = StallEvent(
            agent_id="w1", state=AgentState.STALLED, screen_text="", prompt_type=""
        )
        result = run_monitor_loop(
            "w1",
            pm,
            hb,
            sd,
            max_retries=2,
            max_runtime=9999,
            poll_interval=0,
        )
        assert result.final_state == "failed"
        assert result.retry_count == 3  # exceeded max_retries=2


class TestMonitorLoopMaxRuntime:
    """Agent exceeds max_runtime."""

    def test_returns_failed(self, pm, hb, sd):
        sd.check_agent.return_value = None

        with patch("phalanx.monitor.lifecycle.time") as mock_time:
            call_count = [0]

            def fake_time():
                call_count[0] += 1
                if call_count[0] <= 1:
                    return 0
                return 10000

            mock_time.time = fake_time
            mock_time.sleep = lambda _: None

            result = run_monitor_loop(
                "w1",
                pm,
                hb,
                sd,
                max_retries=3,
                max_runtime=100,
                poll_interval=0,
            )
        assert result.final_state == "failed"
        pm.kill_agent.assert_called_once_with("w1")


class TestMonitorResultDict:
    """MonitorResult.to_dict() serialization."""

    def test_to_dict(self):
        r = MonitorResult(
            agent_id="w1",
            final_state="dead",
            retry_count=2,
            elapsed_seconds=45.67,
        )
        d = r.to_dict()
        assert d["agent_id"] == "w1"
        assert d["status"] == "dead"
        assert d["retry_count"] == 2
        assert d["elapsed_seconds"] == 45.7
