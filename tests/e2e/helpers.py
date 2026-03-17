"""Timing constants and wait helpers for E2E tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

PHALANX_SOURCE = Path(__file__).parent.parent.parent
PHALANX_VENV = PHALANX_SOURCE / ".venv"

# --- Timing constants ---
TEST_POLL_INTERVAL = 2
TEST_GRACE_PERIOD = 30
TEST_IDLE_TIMEOUT = 15
TEST_IDLE_TIMEOUT_DEFAULT = 120
AGENT_COMPLETE_DELAY = 2

SINGLE_AGENT_COMPLETE_TIMEOUT = 50
TEAM_COMPLETE_TIMEOUT = 65

# Allow CI to scale timeouts via env var
_M = float(os.environ.get("PHALANX_E2E_TIMEOUT_MULTIPLIER", "1"))
SINGLE_AGENT_COMPLETE_TIMEOUT = int(SINGLE_AGENT_COMPLETE_TIMEOUT * _M)
TEAM_COMPLETE_TIMEOUT = int(TEAM_COMPLETE_TIMEOUT * _M)


def wait_for_status(db, agent_id: str, target_status: str, timeout: float = 60, poll: float = 0.5):
    """Poll DB until agent reaches target_status or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        agent = db.get_agent(agent_id)
        if agent and agent["status"] == target_status:
            return agent
        time.sleep(poll)
    # Final check
    agent = db.get_agent(agent_id)
    current = agent["status"] if agent else "NOT_FOUND"
    raise TimeoutError(
        f"Agent {agent_id} did not reach status '{target_status}' within {timeout}s "
        f"(current: {current})"
    )


def wait_for_team_status(db, team_id: str, target_status: str, timeout: float = 65, poll: float = 0.5):
    """Poll DB until team reaches target_status or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        team = db.get_team(team_id)
        if team and team["status"] == target_status:
            return team
        time.sleep(poll)
    team = db.get_team(team_id)
    current = team["status"] if team else "NOT_FOUND"
    raise TimeoutError(
        f"Team {team_id} did not reach status '{target_status}' within {timeout}s "
        f"(current: {current})"
    )
