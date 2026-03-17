"""Phase C — crash/failure/negative E2E tests for phalanx.

Test 5:  Worker failure artifact -> status=completed
Test 6:  Agent crashes AFTER writing artifact -> status=completed (Phase 3)
Test 7:  Agent crashes WITHOUT artifact -> status=dead
Test 15: Two monitors same team -> second exits immediately
Test 16: stop_team on completing team -> agents=dead
Test 18: Dead-with-artifact on startup -> reclassified to completed (no tmux)
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

# Ensure helpers and fake_backend are importable
sys.path.insert(0, str(Path(__file__).parent))

from helpers import (
    PHALANX_SOURCE,
    SINGLE_AGENT_COMPLETE_TIMEOUT,
    TEST_IDLE_TIMEOUT_DEFAULT,
    TEST_POLL_INTERVAL,
    wait_for_status,
    wait_for_team_status,
)

sys.path.insert(0, str(PHALANX_SOURCE))

from conftest import run_monitor_background


# ---------------------------------------------------------------------------
# Test 5 — Worker failure artifact -> status=completed
# ---------------------------------------------------------------------------

def test_worker_fail_artifact_completed(
    fake_registry, state_db, process_manager, phalanx_root,
):
    """Single agent writes failure artifact, grace timer fires, status=completed.
    artifact_status must be 'failure', status must be 'completed'."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector

    fb = fake_registry("fake-fail-005", behavior="fail", delay=2)

    team_id = "team-e2e-005"
    agent_id = "lead-e2e-005"

    state_db.create_team(team_id, "Test worker failure artifact")
    state_db.create_agent(agent_id, team_id, task="fail task", role="lead", backend="fake-fail-005")
    state_db.update_agent(agent_id, status="running")

    proc = process_manager.spawn(
        team_id=team_id, agent_id=agent_id, backend=fb,
        prompt="test prompt fail", auto_approve=True,
    )

    hb = HeartbeatMonitor(idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT)
    sd = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        db=state_db,
    )
    hb.register(agent_id, proc.stream_log)

    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb,
        sd=sd,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Agent should reach completed (failure artifact + grace timer)
    wait_for_status(state_db, agent_id, "completed", timeout=50)

    agent = state_db.get_agent(agent_id)
    assert agent["status"] == "completed"
    assert agent["artifact_status"] == "failure"

    team = state_db.get_team(team_id)
    assert team["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 6 — Agent crash after artifact -> status=completed (Phase 3 dead handler)
# ---------------------------------------------------------------------------

def test_agent_crash_after_artifact_completed(
    fake_registry, state_db, process_manager, heartbeat_monitor,
    stall_detector, phalanx_root,
):
    """Agent writes artifact then exits 0. The process dies (ghost shell).
    The stall detector reports DEAD. The monitor DEAD handler detects the
    artifact and reclassifies to completed.

    Because STARTUP_GRACE_SECONDS=120 and STARTUP_DEAD_THRESHOLD=3, we
    bypass grace by backdating the stall detector's _first_seen timestamp
    and reducing the poll interval so consecutive DEAD checks accumulate
    quickly."""
    fb = fake_registry("fake-complete-exit-006", behavior="complete_and_exit", delay=2)

    team_id = "team-e2e-006"
    agent_id = "lead-e2e-006"

    state_db.create_team(team_id, "Test crash after artifact")
    state_db.create_agent(agent_id, team_id, task="complete and exit", role="lead", backend="fake-complete-exit-006")
    state_db.update_agent(agent_id, status="running")

    proc = process_manager.spawn(
        team_id=team_id, agent_id=agent_id, backend=fb,
        prompt="test prompt complete_and_exit", auto_approve=True,
    )

    heartbeat_monitor.register(agent_id, proc.stream_log)

    # Bypass startup grace: backdate _first_seen so the stall detector
    # thinks this agent has been around for 200+ seconds already.
    stall_detector._first_seen[agent_id] = time.time() - 200

    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=heartbeat_monitor,
        sd=stall_detector,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Wait for completed. The agent exits after ~2s, then needs
    # STARTUP_DEAD_THRESHOLD (3) consecutive DEAD detections at poll_interval (2s)
    # before the monitor acts. Grace timer = 30s. Allow up to 90s for system load.
    wait_for_status(state_db, agent_id, "completed", timeout=90)

    agent = state_db.get_agent(agent_id)
    assert agent["status"] == "completed"
    assert agent["artifact_status"] == "success"


# ---------------------------------------------------------------------------
# Test 7 — Agent crash WITHOUT artifact -> status=dead
# ---------------------------------------------------------------------------

def test_agent_crash_no_artifact_dead(
    fake_registry, state_db, process_manager, phalanx_root,
):
    """Agent crashes (exit 1) without writing artifact.
    Stall detector confirms DEAD after startup grace + threshold.
    Monitor sets status=dead.

    We bypass startup grace by backdating _first_seen and set
    max_ghost_restarts=0 so the ghost handler escalates immediately
    (marks agent as 'failed' or 'dead') instead of entering a restart loop.
    """
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector

    fb = fake_registry("fake-crash-007", behavior="crash", delay=2)

    team_id = "team-e2e-007"
    agent_id = "lead-e2e-007"

    state_db.create_team(team_id, "Test crash no artifact")
    state_db.create_agent(agent_id, team_id, task="crash task", role="lead", backend="fake-crash-007")
    state_db.update_agent(agent_id, status="running")
    # Set max_ghost_restarts=0 so ghost handler immediately escalates
    # instead of auto-restarting in a loop.
    state_db.update_agent(agent_id, max_ghost_restarts=0)

    proc = process_manager.spawn(
        team_id=team_id, agent_id=agent_id, backend=fb,
        prompt="test prompt crash", auto_approve=True,
    )

    hb = HeartbeatMonitor(idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT)
    sd = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        db=state_db,
    )
    hb.register(agent_id, proc.stream_log)

    # Bypass startup grace
    sd._first_seen[agent_id] = time.time() - 200

    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb,
        sd=sd,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # The agent crashes after ~2s. Then consecutive DEAD checks accumulate.
    # After 3 consecutive DEAD at 2s polls, the monitor sees it as dead.
    # Since it has no artifact, it may go through blocked_on_prompt (process_exited)
    # -> ghost handler -> failed (because max_ghost_restarts=0).
    # Wait for either "dead" or "failed" -- both are terminal without artifact.
    deadline = time.time() + 60
    while time.time() < deadline:
        agent = state_db.get_agent(agent_id)
        if agent and agent["status"] in ("dead", "failed"):
            break
        time.sleep(0.5)
    else:
        agent = state_db.get_agent(agent_id)
        current = agent["status"] if agent else "NOT_FOUND"
        raise TimeoutError(
            f"Agent {agent_id} did not reach dead/failed within 60s (current: {current})"
        )

    agent = state_db.get_agent(agent_id)
    assert agent["status"] in ("dead", "failed"), f"Expected dead/failed, got {agent['status']}"
    assert agent["artifact_status"] is None


# ---------------------------------------------------------------------------
# Test 15 — Two monitors same team -> second exits immediately
# ---------------------------------------------------------------------------

def test_two_monitors_same_team_second_exits(
    state_db, process_manager, heartbeat_monitor, stall_detector, phalanx_root,
):
    """Start two monitors for the same team. Second should fail to acquire
    lock and exit immediately. First should still be alive."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector

    team_id = "team-e2e-015"
    agent_id = "lead-e2e-015"

    state_db.create_team(team_id, "Test singleton monitor")
    # Create a running agent so Thread A doesn't exit immediately
    # (monitor exits when active_count == 0)
    state_db.create_agent(agent_id, team_id, task="keep alive", role="lead", backend="fake")
    state_db.update_agent(agent_id, status="running")

    # Thread A: first monitor
    thread_a = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=heartbeat_monitor,
        sd=stall_detector,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Brief pause to let Thread A acquire the lock
    time.sleep(1)

    # Thread B: second monitor (same team), should fail lock and exit
    hb2 = HeartbeatMonitor(idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT)
    sd2 = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb2,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        db=state_db,
    )
    thread_b = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb2,
        sd=sd2,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Thread B should exit within 5s (it can't get the lock)
    thread_b.join(timeout=5)
    assert not thread_b.is_alive(), "Thread B should have exited (lock denied)"

    # Thread A should still be alive (it holds the lock, agent is "running")
    assert thread_a.is_alive(), "Thread A should still be alive"

    # Cleanup: kill the team so Thread A exits
    state_db.update_agent(agent_id, status="dead")
    thread_a.join(timeout=10)


# ---------------------------------------------------------------------------
# Test 16 — stop_team on completing team -> agents=dead
# ---------------------------------------------------------------------------

def test_stop_team_on_completing_agents_dead(
    fake_registry, state_db, process_manager, heartbeat_monitor,
    stall_detector, phalanx_root,
):
    """Agent writes artifact (entering 'completing' via grace timer),
    then stop_team kills it and marks everything dead."""
    from phalanx.team.orchestrator import stop_team

    fb = fake_registry("fake-complete-016", behavior="complete", delay=2)

    team_id = "team-e2e-016"
    agent_id = "lead-e2e-016"

    state_db.create_team(team_id, "Test stop team on completing")
    state_db.create_agent(agent_id, team_id, task="complete then stop", role="lead", backend="fake-complete-016")
    state_db.update_agent(agent_id, status="running")

    proc = process_manager.spawn(
        team_id=team_id, agent_id=agent_id, backend=fb,
        prompt="test prompt complete", auto_approve=True,
    )

    heartbeat_monitor.register(agent_id, proc.stream_log)

    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=heartbeat_monitor,
        sd=stall_detector,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Wait for agent to reach "completing" (artifact written, grace timer active)
    wait_for_status(state_db, agent_id, "completing", timeout=SINGLE_AGENT_COMPLETE_TIMEOUT)

    agent_before = state_db.get_agent(agent_id)
    assert agent_before["status"] == "completing"

    # Now stop the team
    result = stop_team(state_db, process_manager, team_id)

    assert agent_id in result["stopped_agents"]

    agent_after = state_db.get_agent(agent_id)
    assert agent_after["status"] == "dead"

    team_after = state_db.get_team(team_id)
    assert team_after["status"] == "dead"


# ---------------------------------------------------------------------------
# Test 18 — Dead-with-artifact on startup -> reclassified to completed (no tmux)
# ---------------------------------------------------------------------------

def test_dead_with_artifact_startup_sweep_reclassified(
    state_db, process_manager, heartbeat_monitor, stall_detector, phalanx_root,
):
    """Create team + agent in DB with status=dead, artifact_status=success.
    No tmux session. Start monitor. Startup sweep reclassifies to completed.
    Monitor exits because all agents are terminal."""
    team_id = "team-e2e-018"
    agent_id = "lead-e2e-018"

    state_db.create_team(team_id, "Test startup sweep reclassification")
    state_db.create_agent(agent_id, team_id, task="already done", role="lead", backend="fake")
    state_db.update_agent(agent_id, status="dead", artifact_status="success")

    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=heartbeat_monitor,
        sd=stall_detector,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Agent should be reclassified to completed on first poll (startup sweep)
    wait_for_status(state_db, agent_id, "completed", timeout=10)

    agent = state_db.get_agent(agent_id)
    assert agent["status"] == "completed"
    assert agent["artifact_status"] == "success"

    # Monitor should exit quickly since all agents are terminal
    monitor_thread.join(timeout=10)
    assert not monitor_thread.is_alive(), "Monitor should have exited after startup sweep"
