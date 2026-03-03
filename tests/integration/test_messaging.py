"""Integration tests for Message Delivery — IT-061 through IT-066."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from phalanx.comms.messaging import deliver_message, broadcast_message


pytestmark = pytest.mark.integration


class TestIT061_FileBasedDelivery:
    """IT-061: Writes temp file and injects Read and respond instruction."""

    def test_file_based_delivery(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True

        result = deliver_message(pm, "agent-1", "do this task", message_dir=tmp_path)
        assert result is True

        call_args = pm.send_keys.call_args[0]
        assert "Read and respond to the message at:" in call_args[1]

        files = list(tmp_path.glob("msg_agent-1_*.txt"))
        assert len(files) == 1
        assert files[0].read_text() == "do this task"


class TestIT062_MessageRunningAgent:
    """IT-062: message-agent succeeds for a running agent."""

    def test_message_delivered(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True
        result = deliver_message(pm, "running-agent", "hello", message_dir=tmp_path)
        assert result is True


class TestIT063_MessageSuspendedAgent:
    """IT-063: Immediately returns False for dead process."""

    def test_message_fails_dead_agent(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = False
        result = deliver_message(pm, "dead-agent", "hello", message_dir=tmp_path)
        assert result is False


class TestIT064_BroadcastMixedState:
    """IT-064: Correctly delivers to running agents and skips suspended ones."""

    def test_broadcast_mixed(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True

        db = MagicMock()
        db.list_agents.return_value = [
            {"id": "w1", "status": "running"},
            {"id": "w2", "status": "running"},
            {"id": "w3", "status": "dead"},
            {"id": "w4", "status": "suspended"},
        ]

        results = broadcast_message(pm, db, "t1", "update", message_dir=tmp_path)
        assert results["w1"] is True
        assert results["w2"] is True
        assert results["w3"] is False
        assert results["w4"] is False


class TestIT065_JSONOutput:
    """IT-065: Messaging returns properly formatted results."""

    def test_broadcast_returns_dict(self):
        pm = MagicMock()
        pm.send_keys.return_value = True

        db = MagicMock()
        db.list_agents.return_value = [
            {"id": "w1", "status": "running"},
        ]

        results = broadcast_message(pm, db, "t1", "msg")
        assert isinstance(results, dict)
        assert "w1" in results


class TestIT066_SilentDropVerification:
    """IT-066: Sending to finished agent — send_keys succeeds but message is lost."""

    def test_silent_drop(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True
        result = deliver_message(pm, "done-agent", "follow up", message_dir=tmp_path)
        assert result is True  # CLI reports success even though TUI ignores it
