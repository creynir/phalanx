"""Tests for messaging module — unit tests with mocked tmux."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from phalanx.comms.messaging import deliver_message, LONG_MESSAGE_THRESHOLD


class TestDeliverMessage:
    @patch("phalanx.comms.messaging.send_keys_to_session", return_value=True)
    def test_short_message_direct(self, mock_send):
        result = deliver_message("phalanx-t1-w1", "do this")
        assert result is True
        mock_send.assert_called_once_with("phalanx-t1-w1", "do this")

    @patch("phalanx.comms.messaging.send_keys_to_session", return_value=True)
    def test_long_message_via_file(self, mock_send, tmp_path):
        long_msg = "x" * (LONG_MESSAGE_THRESHOLD + 100)
        result = deliver_message("phalanx-t1-w1", long_msg, team_dir=tmp_path)
        assert result is True
        call_args = mock_send.call_args[0]
        assert "Read the message at" in call_args[1]
        assert (tmp_path / "messages").exists()

    @patch("phalanx.comms.messaging.send_keys_to_session", return_value=False)
    def test_session_not_found(self, mock_send):
        result = deliver_message("nonexistent", "hello")
        assert result is False
