"""RED-team tests for Phase 2: lead-artifact team shutdown.

All tests in this file are expected to FAIL before any implementation exists.
They cover observable behavior only — DB state changes (team status, agent status),
ProcessManager calls, and monitor loop exit.

Phase 2 covers:
- Lead agent writing a terminal artifact triggers team-wide shutdown
- Team status transitions to `completing` then `completed`
- Workers in suspended/completed state are completed directly (no kill)
- Workers in running/blocked_on_prompt state get grace timers and are killed on expiry
- Monitor exits after team reaches `completed`
- Worker artifacts do NOT trigger team-wide shutdown
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch

from phalanx.monitor.team_monitor import run_team_monitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deps(agents=None):
    """Return a minimal set of mocked collaborators for run_team_monitor."""
    db = MagicMock()
    pm = MagicMock()
    hm = MagicMock()
    sd = MagicMock()

    # Default: no processes discovered, heartbeat returns None
    pm.get_process.return_value = None
    pm.consume_startup_blocked.return_value = None
    pm.discover_agent.return_value = None
    hm.get_state.return_value = None
    hm.check.return_value = None
    sd.check_agent.return_value = None

    # list_agents returns provided agents on first call, then [] to exit loop
    if agents is None:
        agents = []
    db.list_agents.side_effect = [agents, []]

    return db, pm, hm, sd


def _run_one_tick(db, pm, hm, sd, **kwargs):
    """Run run_team_monitor for exactly one meaningful tick then let it exit."""
    run_team_monitor(
        team_id="team-1",
        db=db,
        process_manager=pm,
        heartbeat_monitor=hm,
        stall_detector=sd,
        poll_interval=0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Lead artifact triggers team status = completing
# ---------------------------------------------------------------------------

def test_lead_artifact_triggers_team_completing():
    """When the lead agent writes a terminal artifact, the team status must
    be set to 'completing' in the DB.

    This is distinct from Phase 1 where only the individual agent was set to
    'completing'. Phase 2 requires db.update_team_status(team_id, 'completing').
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    worker = {
        "id": "worker-1",
        "team_id": "team-1",
        "role": "worker",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([lead, worker])

    # Lead has written a terminal artifact
    def _get_agent(agent_id):
        if agent_id == "lead-1":
            return dict(lead, artifact_status="success")
        return dict(worker)

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Observable: team status must be set to 'completing'
    db.update_team_status.assert_any_call("team-1", "completing")


# ---------------------------------------------------------------------------
# 2. Lead artifact starts grace timers for ALL agents
# ---------------------------------------------------------------------------

def test_lead_artifact_starts_grace_timers_for_all_agents():
    """When the lead writes a terminal artifact, ALL running agents (lead +
    workers) must have their status set to 'completing' in the DB.

    The grace timer mechanism is internal (in-memory), but the DB write of
    status='completing' for every running agent is the observable boundary.
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    worker1 = {
        "id": "worker-1",
        "team_id": "team-1",
        "role": "worker",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    worker2 = {
        "id": "worker-2",
        "team_id": "team-1",
        "role": "worker",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([lead, worker1, worker2])

    def _get_agent(agent_id):
        if agent_id == "lead-1":
            return dict(lead, artifact_status="success")
        if agent_id == "worker-1":
            return dict(worker1)
        return dict(worker2)

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # All running agents must be set to 'completing'
    db.update_agent.assert_any_call("lead-1", status="completing")
    db.update_agent.assert_any_call("worker-1", status="completing")
    db.update_agent.assert_any_call("worker-2", status="completing")


# ---------------------------------------------------------------------------
# 3. Lead artifact: suspended worker completed directly (no kill)
# ---------------------------------------------------------------------------

def test_lead_artifact_suspended_worker_completed_directly():
    """When the lead writes a terminal artifact, a worker already in 'suspended'
    state must be set to 'completed' directly — no kill_agent call for it.

    Suspended workers have no live process to kill; they should be skipped
    straight to 'completed' without being put through the grace timer.
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    suspended_worker = {
        "id": "worker-1",
        "team_id": "team-1",
        "role": "worker",
        "status": "suspended",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([lead, suspended_worker])

    def _get_agent(agent_id):
        if agent_id == "lead-1":
            return dict(lead, artifact_status="success")
        return dict(suspended_worker)

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Suspended worker must be completed directly
    db.update_agent.assert_any_call("worker-1", status="completed")

    # kill_agent must NOT be called for the suspended worker
    kill_calls_for_worker = [
        c for c in pm.kill_agent.call_args_list
        if c.args and c.args[0] == "worker-1"
    ]
    assert len(kill_calls_for_worker) == 0, (
        "kill_agent must not be called for a suspended worker during team shutdown"
    )


# ---------------------------------------------------------------------------
# 4. Lead artifact: blocked_on_prompt worker gets grace timer
# ---------------------------------------------------------------------------

def test_lead_artifact_blocked_worker_gets_grace_timer():
    """When the lead writes a terminal artifact, a worker in 'blocked_on_prompt'
    state must receive a grace timer (status set to 'completing'), NOT be
    completed immediately.

    The worker process is still alive; it needs the grace timer flow.
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    blocked_worker = {
        "id": "worker-1",
        "team_id": "team-1",
        "role": "worker",
        "status": "blocked_on_prompt",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([lead, blocked_worker])

    def _get_agent(agent_id):
        if agent_id == "lead-1":
            return dict(lead, artifact_status="success")
        return dict(blocked_worker)

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Worker must enter 'completing' (grace timer started), NOT 'completed' directly
    db.update_agent.assert_any_call("worker-1", status="completing")

    # Must NOT be immediately completed (grace timer has not expired yet)
    immediate_completed = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="completed")
    ]
    assert len(immediate_completed) == 0, (
        "blocked_on_prompt worker must NOT be immediately completed; "
        "it should enter 'completing' with a grace timer"
    )


# ---------------------------------------------------------------------------
# 5. All grace timers expired → agents killed, team status = completed
# ---------------------------------------------------------------------------

def test_all_grace_expired_team_completed():
    """When the team is in 'completing' and all agent grace timers have expired,
    all agents must be killed, set to 'completed', and the team status must
    be updated to 'completed'.
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "completing",
        "artifact_status": "success",
        "updated_at": 0,
    }
    worker = {
        "id": "worker-1",
        "team_id": "team-1",
        "role": "worker",
        "status": "completing",
        "artifact_status": None,
        "updated_at": 0,
    }

    db, pm, hm, sd = _make_deps([lead, worker])

    def _get_agent(agent_id):
        if agent_id == "lead-1":
            return dict(lead)
        return dict(worker)

    db.get_agent.side_effect = _get_agent

    # Both processes alive so startup sweep arms timers
    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = True
    pm.get_process.return_value = mock_proc

    # Sweep arms at T=1000, main-loop checks at T=1031 (expired)
    with patch("phalanx.monitor.team_monitor.time") as mock_time:
        mock_time.time.side_effect = [1000.0, 1000.0, 1031.0, 1031.0]
        mock_time.sleep = time.sleep
        _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Both agents killed and completed
    pm.kill_agent.assert_any_call("lead-1")
    pm.kill_agent.assert_any_call("worker-1")
    db.update_agent.assert_any_call("lead-1", status="completed")
    db.update_agent.assert_any_call("worker-1", status="completed")

    # Team must be marked completed (not just 'dead')
    db.update_team_status.assert_any_call("team-1", "completed")


# ---------------------------------------------------------------------------
# 6. Monitor exits after team reaches completed
# ---------------------------------------------------------------------------

def test_monitor_exits_after_team_completed():
    """After the team transitions to 'completed', the monitor must exit the
    main loop and not continue polling.

    Observable: after the team is marked 'completed', db.list_agents must NOT
    be called again (no extra poll iterations).
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "completing",
        "artifact_status": "success",
        "updated_at": 0,
    }

    # Only one agent in completing — already has grace timer expired scenario
    db, pm, hm, sd = _make_deps([lead])
    db.get_agent.return_value = dict(lead)

    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = True
    pm.get_process.return_value = mock_proc

    with patch("phalanx.monitor.team_monitor.time") as mock_time:
        mock_time.time.side_effect = [1000.0, 1031.0]
        mock_time.sleep = time.sleep
        _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Team must be marked completed
    db.update_team_status.assert_any_call("team-1", "completed")

    # list_agents must have been called only once (first tick that finds the
    # completing agent, transitions to completed, then breaks out of the loop).
    # If the loop continued, it would call list_agents a second time with the
    # empty side_effect which would also exit — but the key is the team_status
    # update to 'completed' must happen, not 'dead'.
    completed_calls = [
        c for c in db.update_team_status.call_args_list
        if c == call("team-1", "completed")
    ]
    assert len(completed_calls) >= 1, (
        "Monitor must call update_team_status('team-1', 'completed') when all "
        "completing agents finish, not just exit silently or call 'dead'"
    )

    # Must NOT have called update_team_status with 'dead' — that's the old path
    dead_calls = [
        c for c in db.update_team_status.call_args_list
        if c == call("team-1", "dead")
    ]
    assert len(dead_calls) == 0, (
        "Monitor must use 'completed' (not 'dead') when exiting after team shutdown"
    )


# ---------------------------------------------------------------------------
# 7. Worker artifact does NOT trigger team shutdown
# ---------------------------------------------------------------------------

def test_worker_artifact_does_not_trigger_team_shutdown():
    """When a worker (non-lead) agent writes a terminal artifact, only that
    worker should get a grace timer. The team status must remain 'running'
    and the lead agent must NOT be given a grace timer (status='completing').

    Phase 2 adds lead-vs-worker artifact discrimination. The monitor must log
    a 'worker_artifact_detected' event (Phase 2) when a non-lead agent writes
    an artifact, distinguishing it from the 'lead_artifact_detected' path that
    triggers team shutdown. This event does not exist in the current codebase.
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    worker = {
        "id": "worker-1",
        "team_id": "team-1",
        "role": "worker",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([lead, worker])

    def _get_agent(agent_id):
        if agent_id == "lead-1":
            return dict(lead)
        # Worker has written artifact
        return dict(worker, artifact_status="success")

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Worker gets completing status (Phase 1 behavior preserved in Phase 2)
    db.update_agent.assert_any_call("worker-1", status="completing")

    # Team status must NOT be set to 'completing' — worker artifact doesn't trigger shutdown
    team_completing_calls = [
        c for c in db.update_team_status.call_args_list
        if c == call("team-1", "completing")
    ]
    assert len(team_completing_calls) == 0, (
        "Worker artifact must NOT trigger team status='completing'; "
        "only a lead artifact triggers team-wide shutdown"
    )

    # Lead must NOT receive a grace timer (not set to 'completing')
    lead_completing_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("lead-1", status="completing")
    ]
    assert len(lead_completing_calls) == 0, (
        "Lead agent must NOT be set to 'completing' when only a worker writes an artifact"
    )

    # Phase 2 positive gate: the monitor must log 'worker_artifact_detected' (not
    # 'lead_artifact_detected') when a non-lead agent writes an artifact.
    # This event type is introduced in Phase 2 to make the discrimination explicit
    # and auditable. It does not exist in the current implementation.
    log_event_calls = db.log_event.call_args_list
    worker_artifact_events = [
        c for c in log_event_calls
        if len(c.args) >= 2 and c.args[1] == "worker_artifact_detected"
    ]
    assert len(worker_artifact_events) >= 1, (
        "Phase 2 requires db.log_event to be called with 'worker_artifact_detected' "
        "when a non-lead agent writes an artifact (to distinguish from lead path); "
        f"actual log_event calls: {log_event_calls}"
    )


# ---------------------------------------------------------------------------
# 8. Lead artifact: already-completed worker stays completed (not touched again)
# ---------------------------------------------------------------------------

def test_lead_artifact_already_completed_worker_stays_completed():
    """When the lead writes a terminal artifact, a worker already in 'completed'
    state must not be touched at all — no duplicate status writes, no kill.
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    completed_worker = {
        "id": "worker-1",
        "team_id": "team-1",
        "role": "worker",
        "status": "completed",
        "artifact_status": "success",
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([lead, completed_worker])

    def _get_agent(agent_id):
        if agent_id == "lead-1":
            return dict(lead, artifact_status="success")
        return dict(completed_worker)

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Team shutdown must still be triggered
    db.update_team_status.assert_any_call("team-1", "completing")

    # Already-completed worker must NOT have update_agent called for it at all
    # during the team shutdown path
    worker_status_calls = [
        c for c in db.update_agent.call_args_list
        if c.args and c.args[0] == "worker-1"
    ]
    assert len(worker_status_calls) == 0, (
        "Already-completed worker must not be touched during lead-artifact team shutdown; "
        f"but got calls: {worker_status_calls}"
    )

    # No kill for completed worker
    kill_calls_for_worker = [
        c for c in pm.kill_agent.call_args_list
        if c.args and c.args[0] == "worker-1"
    ]
    assert len(kill_calls_for_worker) == 0, (
        "kill_agent must not be called for an already-completed worker"
    )


# ---------------------------------------------------------------------------
# 9. team_completing event is logged when lead writes artifact
# ---------------------------------------------------------------------------

def test_team_completing_logged_as_event():
    """When the lead agent writes a terminal artifact that triggers team
    shutdown, db.log_event must be called with event type 'team_completing'.

    This ensures the event is observable in the audit log.
    """
    lead = {
        "id": "lead-1",
        "team_id": "team-1",
        "role": "lead",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([lead])
    db.get_agent.return_value = dict(lead, artifact_status="success")

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Observable: log_event must be called with 'team_completing'
    log_event_calls = db.log_event.call_args_list
    team_completing_events = [
        c for c in log_event_calls
        if len(c.args) >= 2 and c.args[1] == "team_completing"
    ]
    assert len(team_completing_events) >= 1, (
        f"db.log_event must be called with 'team_completing' when lead writes artifact; "
        f"actual log_event calls: {log_event_calls}"
    )
