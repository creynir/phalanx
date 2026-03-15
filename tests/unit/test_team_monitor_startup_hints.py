import json
from unittest.mock import MagicMock

from phalanx.monitor.team_monitor import _startup_recovery_hint, _team_auto_approve


def test_startup_recovery_hint_auto_approve_true():
    hint = _startup_recovery_hint(
        agent_id="worker-1",
        backend_name="claude",
        prompt_excerpt="Select login method",
        auto_approve=True,
    )
    assert "resume-agent worker-1 --reply 1" in hint
    assert "auto_approve=false" not in hint


def test_startup_recovery_hint_auto_approve_false():
    hint = _startup_recovery_hint(
        agent_id="worker-1",
        backend_name="claude",
        prompt_excerpt="Select login method",
        auto_approve=False,
    )
    assert "auto_approve=false" in hint
    assert "agent-status worker-1" in hint


def test_team_auto_approve_from_db_config():
    db = MagicMock()
    db.get_team.return_value = {"config": json.dumps({"auto_approve": True})}
    assert _team_auto_approve(db, "team-1") is True

