"""Tests for messaging module — unit tests with mocked ProcessManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from phalanx.comms.messaging import (
    broadcast_message,
    deliver_message,
    LONG_MESSAGE_THRESHOLD,
)


class TestDeliverMessage:
    def test_short_message_via_file(self, tmp_path):
        """All messages are delivered via file to prevent shell injection."""
        pm = MagicMock()
        pm.send_keys.return_value = True

        result = deliver_message(pm, "agent-1", "do this", message_dir=tmp_path)
        assert result is True
        pm.interrupt_agent.assert_not_called()

        call_args = pm.send_keys.call_args[0]
        assert call_args[0] == "agent-1"
        assert "Read and respond to the message at:" in call_args[1]

        files = list(tmp_path.glob("msg_agent-1_*.txt"))
        assert len(files) == 1
        assert files[0].read_text() == "do this"

    def test_long_message_via_file(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True

        long_msg = "x" * (LONG_MESSAGE_THRESHOLD + 100)
        result = deliver_message(pm, "agent-1", long_msg, message_dir=tmp_path)
        assert result is True
        pm.interrupt_agent.assert_not_called()

        call_args = pm.send_keys.call_args[0]
        assert call_args[0] == "agent-1"
        assert "Read and respond to the message at:" in call_args[1]

        files = list(tmp_path.glob("msg_agent-1_*.txt"))
        assert len(files) == 1

    def test_session_not_found(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = False

        result = deliver_message(pm, "nonexistent", "hello", message_dir=tmp_path)
        assert result is False

    def test_no_shell_injection_in_delivery_text(self, tmp_path):
        """Delivery text must not contain the message content inline."""
        pm = MagicMock()
        pm.send_keys.return_value = True

        malicious = 'evil"; rm -rf /;'
        deliver_message(pm, "agent-1", malicious, message_dir=tmp_path)
        call_args = pm.send_keys.call_args[0]
        # The delivery text should not contain the malicious content
        assert "evil" not in call_args[1]
        assert "rm -rf" not in call_args[1]


class TestBroadcastMessage:
    def test_broadcast_sends_to_all_running(self):
        pm = MagicMock()
        pm.send_keys.return_value = True

        db = MagicMock()
        db.list_agents.return_value = [
            {"id": "w0", "status": "running"},
            {"id": "w1", "status": "running"},
            {"id": "w2", "status": "dead"},
        ]

        results = broadcast_message(pm, db, "team-1", "update")
        assert results["w0"] is True
        assert results["w1"] is True
        assert results["w2"] is False

    def test_broadcast_excludes_agent(self):
        pm = MagicMock()
        pm.send_keys.return_value = True

        db = MagicMock()
        db.list_agents.return_value = [
            {"id": "lead-1", "status": "running"},
            {"id": "w0", "status": "running"},
        ]

        results = broadcast_message(pm, db, "team-1", "msg", exclude_agent_id="lead-1")
        assert "lead-1" not in results
        assert results["w0"] is True
