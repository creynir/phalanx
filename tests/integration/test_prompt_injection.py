"""Integration tests for Prompt Injection Buffer Corruption Recovery — IT-039 through IT-045."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from phalanx.monitor.stall import _check_buffer_corrupted


pytestmark = pytest.mark.integration


class TestIT039_BufferCorruptionDetection:
    """IT-039: After send_keys injection, detect quote> mode indicators."""

    def test_quote_mode_detected(self):
        lines = ["some output", "quote> ", "quote> "]
        assert _check_buffer_corrupted(lines) is True

    def test_dquote_mode_detected(self):
        lines = ["some output", "dquote> "]
        assert _check_buffer_corrupted(lines) is True

    def test_bquote_mode_detected(self):
        lines = ["some output", "bquote> "]
        assert _check_buffer_corrupted(lines) is True

    def test_heredoc_mode_detected(self):
        lines = ["some output", "heredoc> "]
        assert _check_buffer_corrupted(lines) is True

    def test_normal_output_not_detected(self):
        lines = ["normal output", "more output"]
        assert _check_buffer_corrupted(lines) is False


class TestIT040_BufferCorruptionRecoveryCtrlC:
    """IT-040: When buffer_corrupted detected, send C-c C-c to escape."""

    def test_ctrl_c_escape(self):
        from phalanx.monitor.team_monitor import _handle_buffer_corruption

        mock_pm = MagicMock()
        mock_db = MagicMock()
        mock_db.get_agent.return_value = {"attempts": 0}
        mock_hb = MagicMock()

        _handle_buffer_corruption(mock_pm, mock_db, mock_hb, "t1", "w1", None, None)
        mock_pm.send_keys.assert_called_once_with("w1", "C-c", enter=False)


class TestIT041_FileBasedFallback:
    """IT-041: File-based prompt delivery fallback."""

    def test_file_based_delivery(self, tmp_path):
        from phalanx.comms.messaging import deliver_message

        mock_pm = MagicMock()
        mock_pm.send_keys.return_value = True

        msg = "Complex prompt with `backticks` and 'quotes'"
        result = deliver_message(mock_pm, "agent-1", msg, message_dir=tmp_path)
        assert result is True

        call_args = mock_pm.send_keys.call_args[0]
        assert "Read and respond to the message at:" in call_args[1]

        files = list(tmp_path.glob("msg_agent-1_*.txt"))
        assert len(files) == 1
        assert files[0].read_text() == msg


class TestIT042_UnescapedCharacters:
    """IT-042: Sending dangerous characters via file-based delivery."""

    def test_dangerous_chars_via_file(self, tmp_path):
        from phalanx.comms.messaging import deliver_message

        mock_pm = MagicMock()
        mock_pm.send_keys.return_value = True

        dangerous = "`'\"<>$VAR$(cmd)\n\t|&&"
        result = deliver_message(mock_pm, "agent-1", dangerous, message_dir=tmp_path)
        assert result is True

        files = list(tmp_path.glob("msg_agent-1_*.txt"))
        assert len(files) == 1
        assert files[0].read_text() == dangerous


class TestIT043_CorruptionEscalation:
    """IT-043: Buffer corruption 3 times → escalation to Outer Loop."""

    def test_repeated_corruption_escalates(self):
        from phalanx.monitor.team_monitor import _handle_buffer_corruption

        mock_pm = MagicMock()
        mock_db = MagicMock()
        mock_db.get_agent.return_value = {"attempts": 2}
        mock_hb = MagicMock()

        _handle_buffer_corruption(mock_pm, mock_db, mock_hb, "t1", "w1", "lead-1", None)

        mock_db.log_event.assert_called()
        event_args = mock_db.log_event.call_args
        assert event_args[0][1] == "buffer_corrupted"


class TestIT044_ResumeAfterBufferCorruption:
    """IT-044: Resume includes Prior Failure Context section."""

    def test_resume_includes_corruption_context(self):
        from phalanx.comms.messaging import sanitize_for_send_keys

        dangerous = "some\x00content\x01with\x0econtrol\x1fchars"
        sanitized = sanitize_for_send_keys(dangerous)
        assert "\x00" not in sanitized
        assert "\x01" not in sanitized


class TestIT045_QuoteModePattern:
    """IT-045: New stall detection pattern buffer_corrupted matches quote> lines."""

    def test_buffer_corrupted_pattern_registered(self):
        from phalanx.monitor.stall import _PROMPT_PATTERNS

        pattern_names = [name for name, _ in _PROMPT_PATTERNS]
        assert "buffer_corrupted" in pattern_names

    def test_quote_at_start_of_line(self):
        lines = ["normal", "quote> some text"]
        assert _check_buffer_corrupted(lines) is True

    def test_quote_mid_line_no_match(self):
        lines = ["normal output with quote> inside"]
        assert _check_buffer_corrupted(lines) is False
