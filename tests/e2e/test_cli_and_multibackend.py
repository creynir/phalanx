"""Phase D — CLI display status mapping and multi-backend routing E2E tests.

Test 19: Completed agent CLI shows 'stopped' (display_status mapping)
Test 20: display_status mapping table validation (completing->running, etc.)
Test 21: Multi-backend routing — lead uses fake-codex, worker uses fake-cursor
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


# ---------------------------------------------------------------------------
# Test 19 — Completed agent CLI shows 'stopped'
# ---------------------------------------------------------------------------

def test_completed_agent_cli_shows_stopped(
    fake_registry, state_db, process_manager, heartbeat_monitor,
    stall_detector, phalanx_root,
):
    """Single agent with behavior='complete' runs to completion.
    After reaching 'completed' in the DB, display_status() must return 'stopped'.
    Also assert the raw DB status IS 'completed' to confirm display_status does the transform."""
    from phalanx.commands._display import display_status
    from phalanx.team.orchestrator import get_team_status

    fb = fake_registry("fake-complete-019", behavior="complete", delay=2)

    team_id = "team-e2e-019"
    agent_id = "lead-e2e-019"

    state_db.create_team(team_id, "Test completed agent shows stopped")
    state_db.create_agent(agent_id, team_id, task="complete task", role="lead", backend="fake-complete-019")
    state_db.update_agent(agent_id, status="running")

    proc = process_manager.spawn(
        team_id=team_id,
        agent_id=agent_id,
        backend=fb,
        prompt="test prompt complete 019",
        auto_approve=True,
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

    # Wait for agent to reach 'completed' status in DB
    wait_for_status(state_db, agent_id, "completed", timeout=SINGLE_AGENT_COMPLETE_TIMEOUT)

    # Verify raw DB status is 'completed'
    agent = state_db.get_agent(agent_id)
    assert agent["status"] == "completed", f"Expected DB status 'completed', got '{agent['status']}'"

    # Now call get_team_status (as CLI team status command does)
    status_data = get_team_status(state_db, team_id)
    assert status_data is not None

    # Find our agent in the status data
    agents_in_status = status_data.get("agents", [])
    assert len(agents_in_status) == 1
    raw_agent_status = agents_in_status[0]["status"]

    # The raw status from get_team_status should be 'completed' (no display mapping yet)
    assert raw_agent_status == "completed", (
        f"Expected raw status 'completed' from get_team_status, got '{raw_agent_status}'"
    )

    # Apply display_status mapping (as CLI does before presenting to user)
    visible_status = display_status(raw_agent_status)
    assert visible_status == "stopped", (
        f"Expected display_status('completed') == 'stopped', got '{visible_status}'"
    )

    # Team should also be completed
    team = state_db.get_team(team_id)
    assert team["status"] == "completed"
    assert display_status(team["status"]) == "stopped"


# ---------------------------------------------------------------------------
# Test 20 — display_status full mapping table validation
# ---------------------------------------------------------------------------

def test_completing_agent_cli_shows_running(
    state_db,
):
    """Validate the full display_status mapping table.

    completed  -> stopped
    suspended  -> stopped
    dead       -> stopped
    completing -> running
    running    -> running
    pending    -> pending

    The 'completing' state is transient; we test it directly via display_status
    without needing a real process.
    """
    from phalanx.commands._display import display_status

    # Full mapping table assertions
    assert display_status("completed") == "stopped", "completed should map to stopped"
    assert display_status("suspended") == "stopped", "suspended should map to stopped"
    assert display_status("dead") == "stopped", "dead should map to stopped"
    assert display_status("completing") == "running", "completing should map to running"
    assert display_status("running") == "running", "running should map to running"
    assert display_status("pending") == "pending", "pending should map to pending"

    # Test 'completing' specifically (the transient state)
    completing_display = display_status("completing")
    assert completing_display == "running", (
        f"display_status('completing') should be 'running', got '{completing_display}'"
    )

    # Also verify via a DB round-trip: create agent, set to completing, check mapping
    team_id = "team-e2e-020"
    agent_id = "lead-e2e-020"

    state_db.create_team(team_id, "Test completing display mapping")
    state_db.create_agent(agent_id, team_id, task="completing test", role="lead", backend="fake")
    state_db.update_agent(agent_id, status="completing")

    agent = state_db.get_agent(agent_id)
    assert agent["status"] == "completing", "DB should store raw 'completing' status"

    # display_status should show 'running' to the user
    user_visible = display_status(agent["status"])
    assert user_visible == "running", (
        f"User-visible status for 'completing' should be 'running', got '{user_visible}'"
    )


# ---------------------------------------------------------------------------
# Test 21 — Multi-backend routing: lead uses fake-codex, worker uses fake-cursor
# ---------------------------------------------------------------------------

def test_multibackend_correct_routing(
    fake_registry, state_db, process_manager, heartbeat_monitor,
    stall_detector, phalanx_root,
):
    """Register two fake backends ('fake-codex' and 'fake-cursor').
    Create a team with lead on fake-codex and worker on fake-cursor.
    Spawn both, run monitor, assert both reach 'completed'.
    Assert each agent's backend field in DB matches the correct backend.
    """
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector

    # Register two distinct fake backends
    fb_codex = fake_registry("fake-codex", behavior="complete", delay=2)
    fb_cursor = fake_registry("fake-cursor", behavior="complete", delay=2)

    team_id = "team-e2e-021"
    lead_id = "lead-e2e-021"
    worker_id = "w0-coder-e2e-021"

    # Create team and agents with different backends
    state_db.create_team(team_id, "Test multi-backend routing")
    state_db.create_agent(lead_id, team_id, task="lead task codex", role="lead", backend="fake-codex")
    state_db.create_agent(worker_id, team_id, task="worker task cursor", role="agent", backend="fake-cursor")
    state_db.update_agent(lead_id, status="running")
    state_db.update_agent(worker_id, status="running")

    # Spawn each agent with its designated backend
    proc_lead = process_manager.spawn(
        team_id=team_id,
        agent_id=lead_id,
        backend=fb_codex,
        prompt="lead prompt for codex backend",
        auto_approve=True,
    )
    proc_worker = process_manager.spawn(
        team_id=team_id,
        agent_id=worker_id,
        backend=fb_cursor,
        prompt="worker prompt for cursor backend",
        auto_approve=True,
    )

    # Create fresh heartbeat monitor and stall detector for this test
    hb = HeartbeatMonitor(idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT)
    sd = StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=hb,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        db=state_db,
    )

    # Register both agents with heartbeat monitor
    hb.register(lead_id, proc_lead.stream_log)
    hb.register(worker_id, proc_worker.stream_log)

    # Start monitor
    monitor_thread = run_monitor_background(
        team_id=team_id,
        db=state_db,
        pm=process_manager,
        hb=hb,
        sd=sd,
        poll_interval=TEST_POLL_INTERVAL,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        lead_agent_id=lead_id,
        phalanx_root=phalanx_root,
    )

    # Wait for both agents to reach 'completed'
    wait_for_status(state_db, worker_id, "completed", timeout=SINGLE_AGENT_COMPLETE_TIMEOUT)
    wait_for_status(state_db, lead_id, "completed", timeout=TEAM_COMPLETE_TIMEOUT)

    # Assert both agents completed successfully
    lead_agent = state_db.get_agent(lead_id)
    worker_agent = state_db.get_agent(worker_id)

    assert lead_agent["status"] == "completed", f"Lead status={lead_agent['status']}"
    assert worker_agent["status"] == "completed", f"Worker status={worker_agent['status']}"

    # Assert each agent's backend field in DB is correct
    assert lead_agent["backend"] == "fake-codex", (
        f"Lead backend should be 'fake-codex', got '{lead_agent['backend']}'"
    )
    assert worker_agent["backend"] == "fake-cursor", (
        f"Worker backend should be 'fake-cursor', got '{worker_agent['backend']}'"
    )

    # Assert the backends are distinct (key multi-backend assertion)
    assert lead_agent["backend"] != worker_agent["backend"], (
        "Lead and worker should use different backends"
    )

    # Assert both have success artifacts (confirming they ran their scripts correctly)
    assert lead_agent["artifact_status"] == "success", (
        f"Lead artifact_status should be 'success', got '{lead_agent['artifact_status']}'"
    )
    assert worker_agent["artifact_status"] == "success", (
        f"Worker artifact_status should be 'success', got '{worker_agent['artifact_status']}'"
    )

    # Team should be completed
    team = state_db.get_team(team_id)
    assert team["status"] == "completed"
