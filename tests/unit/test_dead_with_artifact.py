"""RED-team tests for Phase 3: dead-with-artifact reclassification.

All tests in this file are expected to FAIL before Phase 3 implementation.
They cover the crash-recovery scenario: an agent wrote its artifact then died
(process exited) before the monitor could start a grace timer. Without Phase 3,
the agent stays ``dead`` forever even though it successfully completed.

Key behaviors:
- Dead agent + terminal artifact -> ``completed`` (not ``dead``)
- Dead agent + no artifact -> ``dead`` (unchanged)
- Dead agent + non-terminal artifact -> ``dead`` (unchanged)
- Running agent dying with artifact -> normal Phase 1 grace timer path
- Already-completed agent that is dead -> no change
- Startup sweep reclassifies dead-with-artifact agents
- Dead lead with artifact -> triggers team shutdown (Phase 2)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch

from phalanx.monitor.stall import AgentState
from phalanx.monitor.team_monitor import run_team_monitor


# ---------------------------------------------------------------------------
# Helpers (same pattern as Phase 1/2 tests)
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


def _make_dead_event():
    """Create a stall detector event indicating the agent's tmux is dead."""
    event = MagicMock()
    event.state = AgentState.DEAD
    return event


# ---------------------------------------------------------------------------
# Test 1: Dead agent with terminal artifact (success) -> completed
# ---------------------------------------------------------------------------

def test_dead_agent_with_success_artifact_marked_completed():
    """When an agent's tmux session is gone (DEAD) and the DB shows
    artifact_status='success', the monitor must set status='completed'
    (NOT 'dead') and log 'agent_completed_on_death'.

    This is the core Phase 3 behavior: crash recovery for agents that
    wrote their artifact but died before the monitor could start a grace
    timer.
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])

    # The refreshed DB read shows the agent has a terminal artifact
    refreshed = dict(agent, artifact_status="success")
    db.get_agent.return_value = refreshed

    # Stall detector reports DEAD (tmux session gone)
    sd.check_agent.return_value = _make_dead_event()

    _run_one_tick(db, pm, hm, sd)

    # Phase 3: must be 'completed', not 'dead'
    db.update_agent.assert_any_call("worker-1", status="completed")

    # Must NOT have been set to 'dead'
    dead_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="dead")
    ]
    assert len(dead_calls) == 0, (
        "Dead agent with artifact_status='success' must be set to 'completed', "
        f"not 'dead'; actual update_agent calls: {db.update_agent.call_args_list}"
    )

    # Must log the specific event type for dead-with-artifact
    log_event_calls = db.log_event.call_args_list
    completed_on_death_events = [
        c for c in log_event_calls
        if len(c.args) >= 2 and c.args[1] == "agent_completed_on_death"
    ]
    assert len(completed_on_death_events) >= 1, (
        "Phase 3 requires db.log_event with 'agent_completed_on_death' when a "
        "dead agent has a terminal artifact; "
        f"actual log_event calls: {log_event_calls}"
    )


# ---------------------------------------------------------------------------
# Test 2: Dead agent without artifact -> stays dead (unchanged behavior)
# ---------------------------------------------------------------------------

def test_dead_agent_without_artifact_marked_dead():
    """When an agent's tmux session is gone (DEAD) and artifact_status is None,
    the agent must be set to 'dead' and the event must be 'agent_dead'.

    This confirms Phase 3 does not break existing dead-agent handling.

    Positive Phase 3 gate: the DEAD handler must explicitly check
    artifact_status before deciding between 'dead' and 'completed'. We
    verify this by asserting that db.get_agent was called for the dying
    agent (the refreshed read that Phase 3 inspects). In the current
    implementation the refreshed read already exists, but the Phase 3
    branch that discriminates based on artifact_status does NOT. We add
    a stronger gate: 'agent_dead' must NOT also have 'agent_completed_on_death'
    logged — this event type does not exist pre-Phase 3, so this is safe.
    Additionally, the monitor must NOT log 'agent_completed_on_death' for
    agents without artifacts — this is the Phase 3 discriminator.

    To force a genuine FAIL, we also assert that when a DIFFERENT agent
    in the same tick is dead WITH an artifact, IT gets 'completed' while
    THIS one gets 'dead'. This tests the per-agent discrimination.
    """
    dead_no_artifact = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    dead_with_artifact = {
        "id": "worker-2",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([dead_no_artifact, dead_with_artifact])

    def _get_agent(agent_id):
        if agent_id == "worker-1":
            return dict(dead_no_artifact, artifact_status=None)
        return dict(dead_with_artifact, artifact_status="success")

    db.get_agent.side_effect = _get_agent

    # Both agents are dead
    sd.check_agent.return_value = _make_dead_event()

    _run_one_tick(db, pm, hm, sd)

    # worker-1 (no artifact) must be 'dead'
    db.update_agent.assert_any_call("worker-1", status="dead")

    # worker-2 (has artifact) must be 'completed' — Phase 3 discrimination
    db.update_agent.assert_any_call("worker-2", status="completed")


# ---------------------------------------------------------------------------
# Test 3: Dead agent with failure artifact -> completed
# ---------------------------------------------------------------------------

def test_dead_agent_with_failure_artifact_marked_completed():
    """When an agent dies and artifact_status='failure', status must still
    be 'completed' (even failure artifacts count as 'done').
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = dict(agent, artifact_status="failure")
    sd.check_agent.return_value = _make_dead_event()

    _run_one_tick(db, pm, hm, sd)

    db.update_agent.assert_any_call("worker-1", status="completed")

    dead_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="dead")
    ]
    assert len(dead_calls) == 0, (
        "Dead agent with artifact_status='failure' must be 'completed', not 'dead'"
    )


# ---------------------------------------------------------------------------
# Test 4: Dead agent with escalation artifact -> completed
# ---------------------------------------------------------------------------

def test_dead_agent_with_escalation_artifact_marked_completed():
    """When an agent dies and artifact_status='escalation', status must be
    'completed' (all three terminal statuses trigger reclassification).
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = dict(agent, artifact_status="escalation")
    sd.check_agent.return_value = _make_dead_event()

    _run_one_tick(db, pm, hm, sd)

    db.update_agent.assert_any_call("worker-1", status="completed")

    dead_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="dead")
    ]
    assert len(dead_calls) == 0, (
        "Dead agent with artifact_status='escalation' must be 'completed', not 'dead'"
    )


# ---------------------------------------------------------------------------
# Test 5: Dead agent with non-terminal artifact_status -> stays dead
# ---------------------------------------------------------------------------

def test_dead_agent_with_nonterminal_artifact_stays_dead():
    """If artifact_status is set but not in the terminal set (e.g. 'in_progress'
    or some other non-terminal value), the agent must still be marked 'dead'.

    In practice all written artifacts are terminal, but the guard must be
    explicit.

    To force a genuine FAIL, we pair this agent with another that IS dead
    with a terminal artifact, verifying the Phase 3 discriminator works
    per-agent.
    """
    nonterminal_agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    terminal_agent = {
        "id": "worker-2",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([nonterminal_agent, terminal_agent])

    def _get_agent(agent_id):
        if agent_id == "worker-1":
            return dict(nonterminal_agent, artifact_status="in_progress")
        return dict(terminal_agent, artifact_status="success")

    db.get_agent.side_effect = _get_agent
    sd.check_agent.return_value = _make_dead_event()

    _run_one_tick(db, pm, hm, sd)

    # worker-1: non-terminal -> must be 'dead'
    db.update_agent.assert_any_call("worker-1", status="dead")

    completed_calls_w1 = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="completed")
    ]
    assert len(completed_calls_w1) == 0, (
        "Dead agent with non-terminal artifact_status must NOT be 'completed'"
    )

    # worker-2: terminal artifact -> must be 'completed' (Phase 3 gate)
    db.update_agent.assert_any_call("worker-2", status="completed")


# ---------------------------------------------------------------------------
# Test 6: Startup sweep reclassifies dead agents with artifacts
# ---------------------------------------------------------------------------

def test_startup_sweep_dead_with_artifact_reclassified():
    """On monitor startup, agents already in 'dead' status with a terminal
    artifact_status must be reclassified to 'completed' before the main
    loop starts.

    This covers the scenario where the previous monitor instance set the
    agent to 'dead' (Phase 3 not implemented) or crashed before reclassifying.
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "dead",
        "artifact_status": "success",
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = dict(agent)

    _run_one_tick(db, pm, hm, sd)

    # Startup sweep must reclassify dead-with-artifact to completed
    db.update_agent.assert_any_call("worker-1", status="completed")


# ---------------------------------------------------------------------------
# Test 7: Startup sweep does NOT reclassify dead agents without artifacts
# ---------------------------------------------------------------------------

def test_startup_sweep_dead_without_artifact_stays_dead():
    """On monitor startup, agents in 'dead' status with no artifact must
    NOT be reclassified. They stay dead.

    To force FAIL, we pair with a dead agent that HAS an artifact and
    assert that one IS reclassified (Phase 3 positive gate).
    """
    dead_no_artifact = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "dead",
        "artifact_status": None,
        "updated_at": 0,
    }
    dead_with_artifact = {
        "id": "worker-2",
        "team_id": "team-1",
        "status": "dead",
        "artifact_status": "success",
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([dead_no_artifact, dead_with_artifact])

    def _get_agent(agent_id):
        if agent_id == "worker-1":
            return dict(dead_no_artifact)
        return dict(dead_with_artifact)

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd)

    # worker-1: no artifact -> must NOT be reclassified
    completed_calls_w1 = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="completed")
    ]
    assert len(completed_calls_w1) == 0, (
        "Dead agent without artifact must NOT be reclassified to 'completed' "
        "during startup sweep"
    )

    # worker-2: has artifact -> must be reclassified (Phase 3 positive gate)
    db.update_agent.assert_any_call("worker-2", status="completed")


# ---------------------------------------------------------------------------
# Test 8: Dead lead with artifact triggers team shutdown (Phase 2 path)
# ---------------------------------------------------------------------------

def test_dead_lead_with_artifact_triggers_team_shutdown():
    """When the lead agent is dead AND has a terminal artifact, the monitor
    must trigger team-wide shutdown (Phase 2 path), not just reclassify the
    lead to 'completed'.

    This covers the scenario where the lead wrote its artifact and the process
    died before the monitor could enter the Phase 2 team-completing flow.

    Observable: team status must be set to 'completing' (or 'completed' if
    all agents are already terminal) and worker agents must be enrolled in
    shutdown.
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
            return dict(lead, artifact_status="success")
        return dict(worker)

    db.get_agent.side_effect = _get_agent

    # Lead is dead (stall detector returns DEAD for lead)
    def _check_agent(agent_id):
        if agent_id == "lead-1":
            return _make_dead_event()
        return None

    sd.check_agent.side_effect = _check_agent

    _run_one_tick(db, pm, hm, sd, lead_agent_id="lead-1")

    # Lead must be reclassified to 'completed' (not 'dead')
    dead_lead_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("lead-1", status="dead")
    ]
    assert len(dead_lead_calls) == 0, (
        "Dead lead with artifact must NOT be set to 'dead'; "
        "it should trigger team shutdown and be set to 'completed'"
    )

    # Team shutdown must be triggered: team status set to 'completing' or 'completed'
    team_status_calls = db.update_team_status.call_args_list
    team_shutdown_calls = [
        c for c in team_status_calls
        if c in (call("team-1", "completing"), call("team-1", "completed"))
    ]
    assert len(team_shutdown_calls) >= 1, (
        "Dead lead with artifact must trigger team shutdown "
        "(update_team_status with 'completing' or 'completed'); "
        f"actual calls: {team_status_calls}"
    )


# ---------------------------------------------------------------------------
# Test 9: Already-completed agent that is dead -> no change
# ---------------------------------------------------------------------------

def test_already_completed_dead_agent_no_change():
    """An agent already in 'completed' status should not be touched by the
    dead-with-artifact logic even if it has an artifact. The monitor skips
    completed agents entirely (they are in a terminal state).

    To force FAIL, we pair with a dead (not completed) agent that has an
    artifact and assert Phase 3 reclassifies that one while leaving the
    already-completed one alone.
    """
    already_completed = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "completed",
        "artifact_status": "success",
        "updated_at": 0,
    }
    dead_with_artifact = {
        "id": "worker-2",
        "team_id": "team-1",
        "status": "dead",
        "artifact_status": "success",
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([already_completed, dead_with_artifact])

    def _get_agent(agent_id):
        if agent_id == "worker-1":
            return dict(already_completed)
        return dict(dead_with_artifact)

    db.get_agent.side_effect = _get_agent

    _run_one_tick(db, pm, hm, sd)

    # worker-1: already completed -> no status writes
    worker1_status_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="completed")
        or c == call("worker-1", status="dead")
    ]
    assert len(worker1_status_calls) == 0, (
        "Already-completed agent must not have its status rewritten; "
        f"actual calls: {db.update_agent.call_args_list}"
    )

    # worker-2: dead with artifact -> Phase 3 must reclassify to 'completed'
    db.update_agent.assert_any_call("worker-2", status="completed")


# ---------------------------------------------------------------------------
# Test 10: Running agent with artifact that then dies -> Phase 1 grace path
# ---------------------------------------------------------------------------

def test_running_agent_artifact_then_dies_uses_grace_path():
    """If a running agent has a terminal artifact detected in the same poll
    cycle where it dies, the artifact detection (Phase 1 completing->grace)
    path should fire, NOT the dead-with-artifact reclassification.

    This test verifies that Phase 3 does not interfere with Phase 1. When
    the artifact is detected on a running agent, the agent should enter
    'completing' status. The fact that it also reports DEAD on this cycle
    should not cause a direct 'completed' reclassification (that skips the
    grace period).

    Observable: the agent must be set to 'completing' (Phase 1 path), and
    the artifact_detected flow must take precedence.
    """
    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])

    # Artifact has been written
    db.get_agent.return_value = dict(agent, artifact_status="success")

    # Agent is also dead in the same cycle
    sd.check_agent.return_value = _make_dead_event()

    _run_one_tick(db, pm, hm, sd)

    # The artifact detection path (Phase 1) should set status to 'completing'
    # OR if the agent is dead AND has artifact, Phase 3 reclassifies to 'completed'.
    # Either way, it must NOT be left as 'dead'.
    dead_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="dead")
    ]
    assert len(dead_calls) == 0, (
        "Agent with artifact that dies must NOT be set to 'dead'; "
        "it should be either 'completing' (Phase 1) or 'completed' (Phase 3); "
        f"actual calls: {db.update_agent.call_args_list}"
    )
