"""Tests for messaging module — unit tests with mocked ProcessManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from phalanx.comms.messaging import deliver_message, LONG_MESSAGE_THRESHOLD


class TestDeliverMessage:
    def test_short_message_direct(self):
        pm = MagicMock()
        pm.send_keys.return_value = True

        result = deliver_message(pm, "phalanx-t1-w1", "do this")
        assert result is True
        pm.interrupt_agent.assert_called_once_with("phalanx-t1-w1")
        pm.send_keys.assert_called_once_with("phalanx-t1-w1", "do this", enter=True)

    def test_long_message_via_file(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True

        long_msg = "x" * (LONG_MESSAGE_THRESHOLD + 100)
        result = deliver_message(pm, "phalanx-t1-w1", long_msg, message_dir=tmp_path)
        assert result is True

        pm.interrupt_agent.assert_called_once_with("phalanx-t1-w1")

        call_args = pm.send_keys.call_args[0]
        assert call_args[0] == "phalanx-t1-w1"
        assert "Read the message at" in call_args[1]

        # Verify the file was created and contains the message
        files = list(tmp_path.glob("msg_phalanx-t1-w1_*.txt"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == long_msg

    def test_session_not_found(self):
        pm = MagicMock()
        pm.send_keys.return_value = False

        result = deliver_message(pm, "nonexistent", "hello")
        assert result is False
        pm.send_keys.assert_called_once_with("nonexistent", "hello", enter=True)

    def test_no_interrupt_if_busy_false(self):
        pm = MagicMock()
        pm.send_keys.return_value = True

        result = deliver_message(pm, "phalanx-t1-w1", "do this", interrupt_if_busy=False)
        assert result is True
        pm.interrupt_agent.assert_not_called()
        pm.send_keys.assert_called_once_with("phalanx-t1-w1", "do this", enter=True)
