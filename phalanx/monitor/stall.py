"""Stall detection and automatic retry with exponential backoff."""

from __future__ import annotations

from phalanx.db import Database
from phalanx.process.manager import kill_session


def compute_backoff(attempt: int, base: int = 30, cap: int = 300) -> int:
    """Exponential backoff: min(base * 2^attempt, cap)."""
    return min(base * (2 ** attempt), cap)


def handle_stall(
    db: Database,
    agent_id: str,
    team_id: str,
) -> str:
    """Handle a stalled agent. Returns new status: 'retrying' or 'failed'.

    1. Kill the tmux session
    2. If attempts < max_retries: increment, return 'retrying'
    3. Else: mark failed, return 'failed'
    """
    agent = db.get_agent(agent_id)
    if agent is None:
        return "failed"

    if agent["tmux_session"]:
        kill_session(agent["tmux_session"])

    attempts = agent["attempts"] + 1
    max_retries = agent["max_retries"]

    if attempts >= max_retries:
        db.update_agent(agent_id, status="failed", attempts=attempts)
        db.insert_event("agent_failed", team_id=team_id, agent_id=agent_id,
                        payload={"reason": "max_retries_exhausted", "attempts": attempts})
        return "failed"

    backoff = compute_backoff(attempts)
    db.update_agent(agent_id, status="stalled", attempts=attempts)
    db.insert_event("agent_stalled", team_id=team_id, agent_id=agent_id,
                    payload={"attempt": attempts, "backoff_seconds": backoff})
    return "retrying"
