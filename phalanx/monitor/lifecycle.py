"""Agent lifecycle state machine."""

from __future__ import annotations

from phalanx.db import Database
from phalanx.process.manager import session_exists

VALID_TRANSITIONS = {
    "pending":  {"running"},
    "running":  {"idle", "stalled", "dead", "failed"},
    "idle":     {"dead", "running"},
    "stalled":  {"running", "failed", "dead"},
    "dead":     {"running"},  # resume
    "failed":   set(),        # terminal
}


def can_transition(current: str, target: str) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())


def transition_agent(db: Database, agent_id: str, new_status: str, **extra) -> bool:
    """Attempt a state transition. Returns True if valid and applied."""
    agent = db.get_agent(agent_id)
    if agent is None:
        return False

    current = agent["status"]
    if not can_transition(current, new_status):
        return False

    db.update_agent(agent_id, status=new_status, **extra)
    return True


def check_agent_health(db: Database, agent_id: str) -> str:
    """Check if an agent's tmux session is still alive and update status accordingly.

    Returns the current/new status.
    """
    agent = db.get_agent(agent_id)
    if agent is None:
        return "unknown"

    if agent["status"] in ("dead", "failed", "pending"):
        return agent["status"]

    tmux_session = agent.get("tmux_session")
    if tmux_session and not session_exists(tmux_session):
        if agent.get("artifact_status"):
            transition_agent(db, agent_id, "idle")
            return "idle"
        else:
            transition_agent(db, agent_id, "dead")
            return "dead"

    return agent["status"]
