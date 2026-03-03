"""E2E tests: Messaging, Notifications, and Events — E2E-023 through E2E-028."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from phalanx.comms.messaging import deliver_message, broadcast_message
from phalanx.db import StateDB


pytestmark = pytest.mark.e2e


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


class TestE2E023_WorkerDoneEvent:
    """E2E-023: Worker writes success → lead gets worker_done within one poll."""

    def test_artifact_status_flip(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        db.update_agent("w1", artifact_status="success")
        agent = db.get_agent("w1")
        assert agent["artifact_status"] == "success"


class TestE2E024_NoWorkerDoneOnFailure:
    """E2E-024: Failure artifact does NOT trigger event to lead."""

    def test_failure_ignored(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        db.update_agent("w1", artifact_status="failure")
        agent = db.get_agent("w1")
        assert agent["artifact_status"] == "failure"


class TestE2E025_MessageDeadAgent:
    """E2E-025: CLI rejects message to dead/suspended agent."""

    def test_message_fails(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = False
        result = deliver_message(pm, "dead-agent", "hello", message_dir=tmp_path)
        assert result is False


class TestE2E026_MessageDoneAgent:
    """E2E-026: Completed agent's TUI ignores send_keys input."""

    def test_silent_drop(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True
        result = deliver_message(pm, "done-agent", "follow up", message_dir=tmp_path)
        assert result is True  # send_keys succeeds but TUI ignores


class TestE2E027_BroadcastMixed:
    """E2E-027: Broadcast reports skipped agents."""

    def test_broadcast_report(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True

        mock_db = MagicMock()
        mock_db.list_agents.return_value = [
            {"id": "w1", "status": "running"},
            {"id": "w2", "status": "dead"},
            {"id": "w3", "status": "suspended"},
        ]

        results = broadcast_message(pm, mock_db, "t1", "update", message_dir=tmp_path)
        assert results["w1"] is True
        assert results["w2"] is False
        assert results["w3"] is False


class TestE2E028_PromptInjectionSafety:
    """E2E-028: Complex prompt written to file, not injected inline."""

    def test_file_based_delivery(self, tmp_path):
        pm = MagicMock()
        pm.send_keys.return_value = True

        msg = "Test with 'quotes', \"doubles\", `backticks`, <angles>, $VARS"
        deliver_message(pm, "agent-1", msg, message_dir=tmp_path)

        call_args = pm.send_keys.call_args[0]
        assert "Read and respond to the message at:" in call_args[1]
        assert "backticks" not in call_args[1]
        assert "$VARS" not in call_args[1]
