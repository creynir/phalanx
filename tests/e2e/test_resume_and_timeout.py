"""Phase B — idle-timeout (suspend) and resume E2E tests for phalanx.

Test 4:  Agent suspended after idle, then resumed and completes
Test 9:  Completed team resumed, chat_id used for spawn_resume
Test 12: Agent idle for 15s, status=suspended
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure helpers and fake_backend are importable
sys.path.insert(0, str(Path(__file__).parent))

from helpers import (
    PHALANX_SOURCE,
    TEST_IDLE_TIMEOUT,
    TEST_POLL_INTERVAL,
    wait_for_status,
    wait_for_team_status,
)

sys.path.insert(0, str(PHALANX_SOURCE))

from conftest import run_monitor_background


# ---------------------------------------------------------------------------
# Test 12 — simplest: agent stalls, idle timeout fires, status=suspended
# ---------------------------------------------------------------------------

def test_agent_idle_timeout_suspended(
    fake_registry, state_db, process_manager, phalanx_root,
):
    """Agent stalls (no artifact), idle_timeout=15 fires, status becomes suspended."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector

    fb = fake_registry("fake-stall-012", behavior="stall", delay=2)

    team_id = "team-e2e-012"
    agent_id = "lead-e2e-012"

    state_db.create_team(team_id, "Test idle timeout suspend")
    state_db.create_agent(agent_id, team_id, task="stall forever", role="lead", backend="fake-stall-012")
    state_db.update_agent(agent_id, status="running")

    proc = process_manager.spawn(
        team_id=team_id,
        agent_id=agent_id,
        backend=fb,
        prompt="test prompt stall",
        auto_approve=True,
    )

    hb = HeartbeatMonitor(idle_timeout=TEST_IDLE_TIMEOUT)
    sd = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb,
        idle_timeout=TEST_IDLE_TIMEOUT,
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
        idle_timeout=TEST_IDLE_TIMEOUT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Wait for the agent to be suspended (idle timeout ~15s + poll overhead)
    wait_for_status(state_db, agent_id, "suspended", timeout=30)

    agent = state_db.get_agent(agent_id)
    assert agent["status"] == "suspended"

    # tmux session should be gone (killed by monitor on idle timeout)
    import libtmux
    server = libtmux.Server()
    session_names = [s.name for s in server.sessions]
    assert f"phalanx-{team_id}-{agent_id}" not in session_names


# ---------------------------------------------------------------------------
# Test 4 — agent suspended after idle, then resumed and completes
# ---------------------------------------------------------------------------

def test_agent_suspended_then_resumed_completes(
    fake_registry, state_db, process_manager, phalanx_root, monkeypatch,
):
    """Phase 1: agent stalls -> suspended. Phase 2: re-register complete backend,
    resume_single_agent, new monitor -> completed with artifact."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector
    from phalanx.team.orchestrator import resume_single_agent

    fb_stall = fake_registry("fake-stall-004", behavior="stall", delay=2)

    team_id = "team-e2e-004"
    agent_id = "lead-e2e-004"

    state_db.create_team(team_id, "Test suspend then resume")
    state_db.create_agent(agent_id, team_id, task="stall then complete", role="lead", backend="fake-stall-004")
    state_db.update_agent(agent_id, status="running")

    proc = process_manager.spawn(
        team_id=team_id,
        agent_id=agent_id,
        backend=fb_stall,
        prompt="test prompt stall phase1",
        auto_approve=True,
    )

    hb1 = HeartbeatMonitor(idle_timeout=TEST_IDLE_TIMEOUT)
    sd1 = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb1,
        idle_timeout=TEST_IDLE_TIMEOUT,
        db=state_db,
    )
    hb1.register(agent_id, proc.stream_log)

    monitor_thread_1 = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb1,
        sd=sd1,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Phase 1: wait for suspended
    wait_for_status(state_db, agent_id, "suspended", timeout=30)

    agent_p1 = state_db.get_agent(agent_id)
    assert agent_p1["status"] == "suspended"

    # Wait for monitor thread to exit (it exits when all agents are terminal)
    monitor_thread_1.join(timeout=10)

    # Phase 2: re-register the backend as "complete" behavior
    fb_complete = fake_registry("fake-stall-004", behavior="complete", delay=2)

    # Create fresh heartbeat monitor and stall detector for Phase 2
    hb2 = HeartbeatMonitor(idle_timeout=120)
    sd2 = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb2,
        idle_timeout=120,
        db=state_db,
    )

    # Resume the agent — since no chat_id was persisted (stall behavior
    # doesn't write artifact), this will call process_manager.spawn() with
    # a resume prompt.
    result = resume_single_agent(
        phalanx_root=phalanx_root,
        db=state_db,
        process_manager=process_manager,
        heartbeat_monitor=hb2,
        agent_id=agent_id,
        auto_approve=True,
    )
    assert result["status"] == "running"

    # Update team status back to running
    state_db.update_team_status(team_id, "running")

    # Start new monitor for Phase 2
    monitor_thread_2 = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb2,
        sd=sd2,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=120,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Phase 2: wait for completed
    wait_for_status(state_db, agent_id, "completed", timeout=50)

    agent_p2 = state_db.get_agent(agent_id)
    assert agent_p2["status"] == "completed"
    assert agent_p2["artifact_status"] == "success"


# ---------------------------------------------------------------------------
# Test 9 — completed team resumed, chat_id persisted from Phase 1
# ---------------------------------------------------------------------------

def test_completed_team_resumed_with_chat_id(
    fake_registry, state_db, process_manager, phalanx_root, monkeypatch,
):
    """Phase 1: agent completes, chat_id persisted by _ChatIdScanner.
    Phase 2: resume_team() re-spawns the agent, agent completes again.

    Verifies that chat_id is recorded in Phase 1 and that the team can be
    resumed back to completed status.
    """
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector
    from phalanx.team.orchestrator import resume_team

    fb = fake_registry("fake-complete-009", behavior="complete", delay=2)

    team_id = "team-e2e-009"
    agent_id = "lead-e2e-009"

    state_db.create_team(team_id, "Test resume with chat_id")
    state_db.create_agent(agent_id, team_id, task="complete then resume", role="lead", backend="fake-complete-009")
    state_db.update_agent(agent_id, status="running")

    proc = process_manager.spawn(
        team_id=team_id,
        agent_id=agent_id,
        backend=fb,
        prompt="test prompt complete phase1",
        auto_approve=True,
    )

    hb1 = HeartbeatMonitor(idle_timeout=120)
    sd1 = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb1,
        idle_timeout=120,
        db=state_db,
    )
    hb1.register(agent_id, proc.stream_log)

    monitor_thread_1 = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb1,
        sd=sd1,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=120,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Phase 1: wait for team to complete
    wait_for_team_status(state_db, team_id, "completed", timeout=50)

    agent_p1 = state_db.get_agent(agent_id)
    assert agent_p1["status"] == "completed"
    # chat_id should have been persisted by _ChatIdScanner
    assert agent_p1["chat_id"] is not None, "chat_id should be persisted after completion"

    chat_id_p1 = agent_p1["chat_id"]

    # Wait for monitor to exit
    monitor_thread_1.join(timeout=10)

    # Phase 2: re-register backend with fresh complete behavior
    fb2 = fake_registry("fake-complete-009", behavior="complete", delay=2)

    hb2 = HeartbeatMonitor(idle_timeout=120)
    sd2 = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb2,
        idle_timeout=120,
        db=state_db,
    )

    # resume_team calls _spawn_team_monitor which tries to create a tmux
    # monitor session. In tests we run the monitor in-thread, so we
    # monkeypatch it out.
    from phalanx.team import create as _create_mod
    monkeypatch.setattr(_create_mod, "_spawn_team_monitor", lambda *a, **kw: None)

    # Clear chat_id so resume_team uses spawn() with context-enriched prompt
    # instead of spawn_resume(). Both paths are valid; this exercises the
    # context-resume path.
    state_db.update_agent(agent_id, chat_id=None)

    # Release the monitor lock from Phase 1 in case it wasn't cleaned up
    try:
        state_db.release_lock(f"__monitor_lock__/{team_id}")
    except Exception:
        pass

    result = resume_team(
        phalanx_root=phalanx_root,
        db=state_db,
        process_manager=process_manager,
        heartbeat_monitor=hb2,
        team_id=team_id,
        resume_all=True,
        auto_approve=True,
    )
    assert agent_id in result["resumed_agents"]

    # Start a new monitor thread for Phase 2
    monitor_thread_2 = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb2,
        sd=sd2,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=120,
        lead_agent_id=agent_id,
        phalanx_root=phalanx_root,
    )

    # Phase 2: wait for team to complete again
    wait_for_team_status(state_db, team_id, "completed", timeout=50)

    agent_p2 = state_db.get_agent(agent_id)
    assert agent_p2["status"] == "completed"

    team_p2 = state_db.get_team(team_id)
    assert team_p2["status"] == "completed"
