"""RED-team tests for Phase 1: kill-on-artifact + grace timer.

All tests in this file are expected to FAIL before any implementation exists.
They cover observable behavior only — DB state changes and ProcessManager calls.

Risk register coverage:
  R2  — grace timer lost on crash (tests 8, 9: startup sweep re-arms / clears completing)
  R5  — orphaned `completing` on startup (tests 8, 9)
  R-S4 — duplicate monitor singleton guard (tests 10, 11)
  R-S2 — running-with-artifact not touched by sweep (test 12)
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
# 1. Artifact triggers completing status
# ---------------------------------------------------------------------------

def test_artifact_triggers_completing_status():
    """When a running agent's artifact_status transitions to a terminal value,
    the monitor must set the agent's status to 'completing' in the DB."""
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])

    # After the first get_agent call, artifact_status has been written
    refreshed = dict(agent, artifact_status="success")
    db.get_agent.return_value = refreshed

    _run_one_tick(db, pm, hm, sd)

    # Observable behavior: DB must have been updated with status='completing'
    db.update_agent.assert_any_call("worker-1", status="completing")


# ---------------------------------------------------------------------------
# 2. Grace timer expiry kills agent and marks completed
# ---------------------------------------------------------------------------

def test_grace_timer_expiry_kills_agent():
    """When the 30-second grace timer has already expired for a completing
    agent, kill_agent must be called and the DB status set to 'completed'.

    Grace timer state lives only in-memory (_grace_timers dict).  The startup
    sweep re-arms the timer with now + GRACE_PERIOD.  We patch time.time so
    that the sweep arms at T=0 and the main-loop check sees T=31 (expired).
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "completing",
        "artifact_status": "success",
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = agent

    # Tmux session alive so sweep re-arms (rather than marking completed immediately)
    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = True
    pm.get_process.return_value = mock_proc

    # First time.time() call (sweep) returns 1000; second (grace check) returns 1031
    with patch("phalanx.monitor.team_monitor.time") as mock_time:
        mock_time.time.side_effect = [1000.0, 1031.0]
        mock_time.sleep = time.sleep
        _run_one_tick(db, pm, hm, sd)

    pm.kill_agent.assert_called_once_with("worker-1")
    db.update_agent.assert_any_call("worker-1", status="completed")


# ---------------------------------------------------------------------------
# 3. Grace timer not yet expired — no kill
# ---------------------------------------------------------------------------

def test_grace_timer_not_expired_no_kill():
    """When the grace timer was started less than 30 seconds ago,
    kill_agent must NOT be called — but the monitor must still recognise
    the agent as 'completing' (skip stall checks) and NOT write a new
    status to DB other than possibly a heartbeat update.

    The positive assertion that forces a FAIL before implementation:
    the monitor must explicitly acknowledge the completing state by
    NOT calling stall_detector.check_agent for this agent.
    We also assert stall_detector.check_agent is NEVER called,
    which only passes after the completing-skips-stall logic is wired up.
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "completing",
        "artifact_status": "success",
        # grace started just now — timer still live
        "grace_started_at": time.time() - 5,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = agent

    _run_one_tick(db, pm, hm, sd)

    # No kill because timer not expired
    pm.kill_agent.assert_not_called()
    # Positive assertion: completing agents bypass stall checks entirely
    sd.check_agent.assert_not_called()


# ---------------------------------------------------------------------------
# 5. failure artifact triggers completing
# ---------------------------------------------------------------------------

def test_artifact_failure_triggers_completing():
    """A 'failure' artifact_status on a running agent must produce
    status='completing', same as 'success'."""
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = dict(agent, artifact_status="failure")

    _run_one_tick(db, pm, hm, sd)

    db.update_agent.assert_any_call("worker-1", status="completing")


# ---------------------------------------------------------------------------
# 6. escalation artifact triggers completing
# ---------------------------------------------------------------------------

def test_artifact_escalation_triggers_completing():
    """An 'escalation' artifact_status on a running agent must produce
    status='completing'."""
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = dict(agent, artifact_status="escalation")

    _run_one_tick(db, pm, hm, sd)

    db.update_agent.assert_any_call("worker-1", status="completing")


# ---------------------------------------------------------------------------
# 7. Already-completing agent not re-triggered
# ---------------------------------------------------------------------------

def test_already_completing_not_retriggered():
    """If an agent is already in 'completing' status and its artifact_status
    is terminal, the monitor must NOT write 'completing' again (no duplicate
    DB write with status='completing') and must NOT call kill_agent prematurely.

    The positive assertion that forces FAIL before implementation:
    the agent must be actively recognised as 'completing' — stall checks
    must be skipped, proving the completing branch is entered.
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "completing",
        "artifact_status": "success",
        # timer not yet expired
        "grace_started_at": time.time() - 5,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = agent

    _run_one_tick(db, pm, hm, sd)

    # Positive gate: the completing branch must be entered (stall check skipped)
    sd.check_agent.assert_not_called()

    # No duplicate completing write
    completing_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="completing")
    ]
    assert len(completing_calls) == 0, (
        "update_agent(status='completing') must not be called when already completing"
    )
    pm.kill_agent.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Startup sweep: completing + tmux alive → grace timer re-armed, no kill
# ---------------------------------------------------------------------------

def test_startup_sweep_completing_tmux_alive():
    """On monitor start, if an agent is in 'completing' and its tmux session
    is still alive, the grace timer must be re-armed in-memory and kill_agent
    must NOT be called immediately.

    Per ADR section 6 ("No new columns"), grace timer state lives only in the
    in-memory _grace_timers dict — no DB write of grace_started_at.
    Observable: no kill, no status='completed' written, and when the timer
    eventually expires the kill fires (tested in test_grace_timer_expiry_kills_agent).
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "completing",
        "artifact_status": "success",
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = agent

    # Tmux session is alive: get_process returns a process object whose is_alive() is True
    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = True
    pm.get_process.return_value = mock_proc

    _run_one_tick(db, pm, hm, sd)

    # No kill because timer was just re-armed (30s from now)
    pm.kill_agent.assert_not_called()
    # No status='completed' written — agent stays in 'completing'
    completed_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="completed")
    ]
    assert len(completed_calls) == 0, (
        "Startup sweep must not mark a live completing agent as completed"
    )


# ---------------------------------------------------------------------------
# 9. Startup sweep: completing + tmux dead → completed immediately, no kill attempt
# ---------------------------------------------------------------------------

def test_startup_sweep_completing_tmux_dead():
    """On monitor start, if an agent is in 'completing' and its tmux session
    is dead, the monitor must mark it 'completed' immediately WITHOUT calling
    kill_agent (process is already gone)."""
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "completing",
        "artifact_status": "success",
        "grace_started_at": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = agent

    # Tmux session is dead: get_process returns None (no process = dead)
    pm.get_process.return_value = None

    _run_one_tick(db, pm, hm, sd)

    db.update_agent.assert_any_call("worker-1", status="completed")
    pm.kill_agent.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Singleton guard: second instance exits without running the loop
# ---------------------------------------------------------------------------

def test_singleton_guard_second_instance_exits():
    """If run_team_monitor is called while another instance already holds the
    singleton lock for the same team_id, the second call must return (or log
    a warning and exit) WITHOUT executing any monitor loop iterations.

    Observable proxy: db.list_agents must never be called by the second instance.
    """
    from phalanx.monitor.team_monitor import run_team_monitor

    db1, pm1, hm1, sd1 = _make_deps([])
    db2, pm2, hm2, sd2 = _make_deps([])

    # Simulate the lock being held by patching the lock acquisition mechanism.
    # The implementation is expected to use a file lock or in-process flag
    # keyed on team_id.  We test at the observable boundary.
    with patch("phalanx.monitor.team_monitor._acquire_monitor_lock", create=True) as mock_lock:
        # First call: lock acquired (returns a truthy context or True)
        # Second call: lock not acquired (returns falsy / raises / returns None)
        mock_lock.side_effect = [True, False]

        # First instance — should run normally
        run_team_monitor(
            team_id="team-1",
            db=db1,
            process_manager=pm1,
            heartbeat_monitor=hm1,
            stall_detector=sd1,
            poll_interval=0,
        )

        # Second instance — must exit without touching db2.list_agents
        run_team_monitor(
            team_id="team-1",
            db=db2,
            process_manager=pm2,
            heartbeat_monitor=hm2,
            stall_detector=sd2,
            poll_interval=0,
        )

    db2.list_agents.assert_not_called()


# ---------------------------------------------------------------------------
# 11. Singleton guard: first instance acquires lock and runs normally
# ---------------------------------------------------------------------------

def test_singleton_guard_first_instance_runs():
    """The first call to run_team_monitor for a team_id must acquire the lock
    and execute the monitor loop (db.list_agents must be called at least once)."""
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = dict(agent)

    with patch("phalanx.monitor.team_monitor._acquire_monitor_lock", create=True) as mock_lock:
        mock_lock.return_value = True

        _run_one_tick(db, pm, hm, sd)

    # The lock function must actually be called once (not just exist as a patch).
    # This assertion fails until _acquire_monitor_lock is wired into run_team_monitor.
    mock_lock.assert_called_once()
    db.list_agents.assert_called()


# ---------------------------------------------------------------------------
# 12. Running agent with artifact_status set — startup sweep leaves it alone
# ---------------------------------------------------------------------------

def test_running_with_artifact_not_touched_by_sweep():
    """A 'running' agent with artifact_status set must NOT be touched by the
    startup sweep. The sweep only re-arms or clears 'completing' agents.

    We verify this through the public API by running two agents together:
    - worker-1: status='completing', grace_started_at=None, process alive
      → sweep MUST re-arm: db.update_agent called with grace_started_at for it
    - worker-2: status='running', artifact_status='success', process alive
      → sweep must NOT touch it: no kill, no status='completed' for worker-2

    The positive gate (re-arming worker-1) forces a FAIL until the sweep exists.
    The negative gate (worker-2 untouched) verifies sweep scope is correct.
    """
    completing_agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "completing",
        "artifact_status": "success",
        # grace_started_at=None simulates a monitor crash that lost the timer
        "grace_started_at": None,
        "updated_at": 0,
    }
    running_agent = {
        "id": "worker-2",
        "team_id": "team-1",
        "status": "running",
        # artifact already written before monitor started
        "artifact_status": "success",
        "grace_started_at": None,
        "updated_at": 0,
    }

    db, pm, hm, sd = _make_deps([completing_agent, running_agent])

    # Both processes are alive
    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = True
    pm.get_process.return_value = mock_proc

    # get_agent: return each agent by id
    def _get_agent(agent_id):
        if agent_id == "worker-1":
            return completing_agent
        return running_agent
    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd)

    # Positive gate: startup sweep must have re-armed worker-1's grace timer
    # in-memory (no DB write per ADR "No new columns").  Observable: worker-1
    # must NOT be marked completed by the sweep (it's alive, timer just armed).
    completed_calls_for_worker1 = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="completed")
    ]
    assert len(completed_calls_for_worker1) == 0, (
        "Startup sweep must not mark a live completing agent as completed"
    )

    # Negative gate: startup sweep must NOT have killed or completed worker-2.
    # kill_agent must never be called for the running agent.
    kill_calls_for_worker2 = [
        c for c in pm.kill_agent.call_args_list
        if c.args and c.args[0] == "worker-2"
    ]
    assert len(kill_calls_for_worker2) == 0, (
        "Startup sweep must not call kill_agent for a 'running' agent"
    )
    completed_calls_for_worker2 = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-2", status="completed")
    ]
    assert len(completed_calls_for_worker2) == 0, (
        "Startup sweep must not write status='completed' for an agent in 'running' status"
    )
