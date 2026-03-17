"""Phase A — happy-path E2E tests for phalanx.

Test 1: Single agent completes, gets killed by grace timer, status=completed
Test 2: Lead + 2 workers, all reach completed
Test 3: Worker completes first, lead completes later, team shutdown
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure helpers and fake_backend are importable
sys.path.insert(0, str(Path(__file__).parent))

from helpers import (
    PHALANX_SOURCE,
    SINGLE_AGENT_COMPLETE_TIMEOUT,
    TEAM_COMPLETE_TIMEOUT,
    TEST_IDLE_TIMEOUT_DEFAULT,
    TEST_POLL_INTERVAL,
    wait_for_status,
    wait_for_team_status,
)

sys.path.insert(0, str(PHALANX_SOURCE))

from conftest import run_monitor_background


def test_single_agent_complete(
    fake_registry, state_db, process_manager, heartbeat_monitor,
    stall_detector, phalanx_root,
):
    """Single agent writes artifact, grace timer fires, agent killed, status=completed."""
    fb = fake_registry("fake-complete", behavior="complete", delay=2)

    team_id = "team-e2e-001"
    agent_id = "lead-e2e-001"

    # Create team + agent in DB
    state_db.create_team(team_id, "Test single agent complete")
    state_db.create_agent(agent_id, team_id, task="complete a task", role="lead", backend="fake-complete")
    state_db.update_agent(agent_id, status="running")

    # Spawn agent in tmux
    proc = process_manager.spawn(
        team_id=team_id,
        agent_id=agent_id,
        backend=fb,
        prompt="test prompt",
        auto_approve=True,
    )

    # Register heartbeat
    heartbeat_monitor.register(agent_id, proc.stream_log)

    # Start monitor in background
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

    # Wait for agent to reach completed status
    wait_for_status(state_db, agent_id, "completed", timeout=SINGLE_AGENT_COMPLETE_TIMEOUT)

    agent = state_db.get_agent(agent_id)
    assert agent["status"] == "completed"
    assert agent["artifact_status"] == "success"

    team = state_db.get_team(team_id)
    assert team["status"] == "completed"

    # artifact.json should exist on disk
    artifact_path = phalanx_root / "teams" / team_id / "agents" / agent_id / "artifact.json"
    assert artifact_path.exists()

    # tmux session should be gone (killed by grace timer)
    import libtmux
    server = libtmux.Server()
    session_names = [s.name for s in server.sessions]
    assert f"phalanx-{team_id}-{agent_id}" not in session_names


def test_lead_and_two_workers_complete(
    fake_registry, state_db, process_manager, heartbeat_monitor,
    stall_detector, phalanx_root,
):
    """Lead + 2 workers all complete. Workers complete first via individual grace,
    lead completes triggering team shutdown."""
    fb_lead = fake_registry("fake-lead", behavior="complete", delay=10)
    fb_worker = fake_registry("fake-worker", behavior="complete", delay=2)

    team_id = "team-e2e-002"
    lead_id = "lead-e2e-002"
    worker1_id = "w0-coder-e2e-002a"
    worker2_id = "w1-coder-e2e-002b"

    # Create team + agents in DB
    state_db.create_team(team_id, "Test lead and two workers")
    state_db.create_agent(lead_id, team_id, task="lead task", role="lead", backend="fake-lead")
    state_db.create_agent(worker1_id, team_id, task="worker1 task", role="agent", backend="fake-worker")
    state_db.create_agent(worker2_id, team_id, task="worker2 task", role="agent", backend="fake-worker")
    state_db.update_agent(lead_id, status="running")
    state_db.update_agent(worker1_id, status="running")
    state_db.update_agent(worker2_id, status="running")

    # Spawn all agents
    proc_lead = process_manager.spawn(team_id, lead_id, fb_lead, prompt="lead prompt", auto_approve=True)
    proc_w1 = process_manager.spawn(team_id, worker1_id, fb_worker, prompt="worker1 prompt", auto_approve=True)
    proc_w2 = process_manager.spawn(team_id, worker2_id, fb_worker, prompt="worker2 prompt", auto_approve=True)

    # Register heartbeats
    heartbeat_monitor.register(lead_id, proc_lead.stream_log)
    heartbeat_monitor.register(worker1_id, proc_w1.stream_log)
    heartbeat_monitor.register(worker2_id, proc_w2.stream_log)

    # Start monitor
    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=heartbeat_monitor,
        sd=stall_detector,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=lead_id,
        phalanx_root=phalanx_root,
    )

    # Wait for all agents to reach completed
    wait_for_status(state_db, worker1_id, "completed", timeout=SINGLE_AGENT_COMPLETE_TIMEOUT)
    wait_for_status(state_db, worker2_id, "completed", timeout=SINGLE_AGENT_COMPLETE_TIMEOUT)
    wait_for_status(state_db, lead_id, "completed", timeout=TEAM_COMPLETE_TIMEOUT)

    # Assert all completed
    for aid in [lead_id, worker1_id, worker2_id]:
        agent = state_db.get_agent(aid)
        assert agent["status"] == "completed", f"Agent {aid} status={agent['status']}"
        assert agent["artifact_status"] == "success", f"Agent {aid} artifact_status={agent['artifact_status']}"

    team = state_db.get_team(team_id)
    assert team["status"] == "completed"


def test_worker_completes_first_lead_later(
    fake_registry, state_db, process_manager, heartbeat_monitor,
    stall_detector, phalanx_root,
):
    """Worker completes first (delay=2), lead later (delay=15).
    Both reach completed, team reaches completed."""
    fb_lead = fake_registry("fake-lead-slow", behavior="complete", delay=15)
    fb_worker = fake_registry("fake-worker-fast", behavior="complete", delay=2)

    team_id = "team-e2e-003"
    lead_id = "lead-e2e-003"
    worker_id = "w0-coder-e2e-003"

    # Create team + agents
    state_db.create_team(team_id, "Test worker completes first")
    state_db.create_agent(lead_id, team_id, task="lead task slow", role="lead", backend="fake-lead-slow")
    state_db.create_agent(worker_id, team_id, task="worker task fast", role="agent", backend="fake-worker-fast")
    state_db.update_agent(lead_id, status="running")
    state_db.update_agent(worker_id, status="running")

    # Spawn
    proc_lead = process_manager.spawn(team_id, lead_id, fb_lead, prompt="lead prompt", auto_approve=True)
    proc_w = process_manager.spawn(team_id, worker_id, fb_worker, prompt="worker prompt", auto_approve=True)

    # Register heartbeats
    heartbeat_monitor.register(lead_id, proc_lead.stream_log)
    heartbeat_monitor.register(worker_id, proc_w.stream_log)

    # Start monitor
    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=heartbeat_monitor,
        sd=stall_detector,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=lead_id,
        phalanx_root=phalanx_root,
    )

    # Worker should complete first
    wait_for_status(state_db, worker_id, "completed", timeout=SINGLE_AGENT_COMPLETE_TIMEOUT)

    # Then lead completes and triggers team shutdown
    wait_for_status(state_db, lead_id, "completed", timeout=TEAM_COMPLETE_TIMEOUT)

    # Assert
    for aid in [lead_id, worker_id]:
        agent = state_db.get_agent(aid)
        assert agent["status"] == "completed", f"Agent {aid} status={agent['status']}"
        assert agent["artifact_status"] == "success", f"Agent {aid} artifact_status={agent['artifact_status']}"

    team = state_db.get_team(team_id)
    assert team["status"] == "completed"
