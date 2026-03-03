"""E2E tests for v1.0.0 features — active tests only.

Covers: TUI Crash Recovery, Buffer Corruption Detection, File-Based Delivery,
Send-Keys Sanitization, Ghost Session Detection, Cost Graceful Degradation,
Rate Limit Detection.

Skipped future stubs (Phase 1.1/1.2) moved to tests/future_backlog/test_v1_e2e_backlog.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from phalanx.monitor.stall import (
    _check_buffer_corrupted,
    _check_process_exited,
    _check_rate_limited,
)


pytestmark = pytest.mark.e2e


# ═══════════════════════════════════════════════════════════════════
# TUI Rendering Crash Recovery (E2E-055)
# ═══════════════════════════════════════════════════════════════════


class TestE2E055_TUICrashGhostAutoRestart:
    """E2E-055: Known poison pill crashes agent → system recovers automatically."""

    def test_ghost_detected_after_crash(self):
        lines = [
            "zsh: command not found: node",
            "zsh: parse error near \\n",
            "user@host$ ",
        ]
        assert _check_process_exited(lines) is True

    def test_auto_restart_triggered(self):
        from phalanx.monitor.team_monitor import _auto_restart_agent

        mock_pm = MagicMock()
        mock_pm._root = "/tmp"
        mock_db = MagicMock()
        mock_hb = MagicMock()

        with patch("phalanx.team.orchestrator.resume_single_agent"):
            _auto_restart_agent(mock_pm, mock_db, mock_hb, "t1", "w1", "lead1", None)
            mock_pm.kill_agent.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# Prompt Injection Buffer Corruption Recovery (E2E-063, E2E-064, E2E-066)
# ═══════════════════════════════════════════════════════════════════


class TestE2E063_BufferCorruptionFileFallback:
    """E2E-063: send_keys causes quote> → system falls back to file delivery."""

    def test_buffer_corruption_detected(self):
        lines = ["quote> some partial input"]
        assert _check_buffer_corrupted(lines) is True


class TestE2E064_LargeResumeFileDelivery:
    """E2E-064: Massive resume prompt uses file-based delivery."""

    def test_file_based_delivery_for_large(self, tmp_path):
        from phalanx.comms.messaging import deliver_message

        pm = MagicMock()
        pm.send_keys.return_value = True
        long_msg = "x" * 2000
        result = deliver_message(pm, "agent-1", long_msg, message_dir=tmp_path)
        assert result is True
        call_args = pm.send_keys.call_args[0]
        assert "Read and respond to the message at:" in call_args[1]


class TestE2E066_SendKeysSanitization:
    """E2E-066: Known dangerous strings sanitized before send_keys."""

    def test_dangerous_via_file(self, tmp_path):
        from phalanx.comms.messaging import deliver_message

        pm = MagicMock()
        pm.send_keys.return_value = True
        msg = "Test `backtick` $(injection) 'quote"
        deliver_message(pm, "agent-1", msg, message_dir=tmp_path)
        call_args = pm.send_keys.call_args[0]
        assert "backtick" not in call_args[1]


# ═══════════════════════════════════════════════════════════════════
# Ghost Session Deep Coverage (E2E-101)
# ═══════════════════════════════════════════════════════════════════


class TestE2E101_SilentExit:
    """E2E-101: Agent exits cleanly but leaves shell → ghost detected."""

    def test_bare_prompt_detected(self):
        lines = ["$ "]
        assert _check_process_exited(lines) is True


# ═══════════════════════════════════════════════════════════════════
# Cost Tracking Failure Modes (E2E-106)
# ═══════════════════════════════════════════════════════════════════


class TestE2E106_GracefulMissingUsage:
    """E2E-106: Agent completes but no token usage parseable → team still works."""

    def test_no_usage_no_crash(self):
        from phalanx.backends.cursor import CursorBackend

        backend = CursorBackend()
        result = backend.parse_token_usage("")
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# API Rate Limit Resilience (E2E-108)
# ═══════════════════════════════════════════════════════════════════


class TestE2E108_RateLimitBackoff:
    """E2E-108: Agent hits rate limit → monitor waits → agent resumes."""

    def test_rate_limit_detected(self):
        lines = ["Error: 429 Too Many Requests"]
        assert _check_rate_limited(lines) is True
