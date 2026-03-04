from unittest.mock import MagicMock
from phalanx.monitor.team_monitor import _should_wake_suspended


def test_should_wake_suspended_success():
    """Wakes up if there is a new feed message from someone else."""
    db = MagicMock()
    # Mock feed message from lead
    db.get_feed.return_value = [{"sender_id": "lead-1", "content": "do this next"}]

    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "artifact_status": "success",
        "updated_at": 1000,
    }

    assert _should_wake_suspended(db, agent) is True
    db.get_feed.assert_called_once_with("team-1", limit=10, since=1000)


def test_should_not_wake_suspended_own_message():
    """Does not wake up if the only new feed messages are from the agent itself."""
    db = MagicMock()
    # Mock feed message from the agent itself
    db.get_feed.return_value = [{"sender_id": "worker-1", "content": "I finished my work"}]

    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "artifact_status": "success",
        "updated_at": 1000,
    }

    assert _should_wake_suspended(db, agent) is False


def test_should_not_wake_suspended_no_feed():
    """Does not wake up if there are no new feed messages."""
    db = MagicMock()
    db.get_feed.return_value = []

    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "artifact_status": "success",
        "updated_at": 1000,
    }

    assert _should_wake_suspended(db, agent) is False


def test_should_not_wake_suspended_wrong_status():
    """Does not wake up if artifact status is not success or escalation."""
    db = MagicMock()

    agent = {"id": "worker-1", "team_id": "team-1", "artifact_status": "failed", "updated_at": 1000}

    assert _should_wake_suspended(db, agent) is False
    db.get_feed.assert_not_called()
