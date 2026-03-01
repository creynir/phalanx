"""Team orchestration: status, stop, result reading."""

from __future__ import annotations

import logging
from pathlib import Path

from phalanx.artifacts.reader import read_agent_artifact, read_team_artifact
from phalanx.db import StateDB
from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)


def get_team_status(db: StateDB, team_id: str) -> dict | None:
    """Get comprehensive team status including all agents."""
    team = db.get_team(team_id)
    if team is None:
        return None

    agents = db.list_agents(team_id)
    return {
        "team": team,
        "agents": agents,
        "agent_count": len(agents),
        "running_count": sum(1 for a in agents if a["status"] == "running"),
    }


def stop_team(
    db: StateDB,
    process_manager: ProcessManager,
    team_id: str,
) -> dict:
    """Stop all agents in a team. Data is preserved for resuming."""
    agents = db.list_agents(team_id)
    stopped = []
    for agent in agents:
        if agent["status"] in ("running", "pending"):
            process_manager.kill_agent(agent["id"])
            db.update_agent(agent["id"], status="dead")
            stopped.append(agent["id"])

    db.update_team_status(team_id, "dead")
    logger.info("Stopped team %s (%d agents killed)", team_id, len(stopped))
    return {"team_id": team_id, "stopped_agents": stopped}


def get_team_result(phalanx_root: Path, team_id: str) -> dict | None:
    """Read the team lead's artifact."""
    artifact = read_team_artifact(phalanx_root, team_id)
    if artifact:
        return artifact.to_dict()
    return None


def get_agent_result(phalanx_root: Path, team_id: str, agent_id: str) -> dict | None:
    """Read a specific agent's artifact."""
    artifact = read_agent_artifact(phalanx_root, team_id, agent_id)
    if artifact:
        return artifact.to_dict()
    return None
