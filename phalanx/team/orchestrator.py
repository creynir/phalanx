"""Team orchestration: status, stop, resume operations."""

from __future__ import annotations

from typing import Any

from phalanx.db import Database
from phalanx.process.manager import kill_session, session_exists
from phalanx.artifacts.reader import read_team_result, list_artifacts
from phalanx.comms.file_lock import release_agent_locks
from phalanx.monitor.lifecycle import check_agent_health


def get_team_status(db: Database, team_id: str) -> dict[str, Any]:
    """Get comprehensive team status including all agents."""
    team = db.get_team(team_id)
    if team is None:
        return {"error": f"Team {team_id} not found"}

    agents = db.list_agents(team_id=team_id)
    for agent in agents:
        check_agent_health(db, agent["id"])

    # Re-fetch after health checks
    agents = db.list_agents(team_id=team_id)

    agent_summaries = []
    for a in agents:
        summary = {
            "id": a["id"],
            "role": a["role"],
            "status": a["status"],
            "model": a["model"],
            "artifact_status": a["artifact_status"],
        }
        agent_summaries.append(summary)

    all_done = all(
        a["status"] in ("idle", "dead", "failed")
        for a in agents
        if a["role"] != "lead"
    )
    lead_done = any(
        a["artifact_status"] is not None
        for a in agents
        if a["role"] == "lead"
    )

    team_status = "running"
    if all_done and lead_done:
        team_status = "completed"
        db.update_team(team_id, status="completed")
    elif all(a["status"] == "failed" for a in agents if a["role"] != "lead"):
        team_status = "failed"
        db.update_team(team_id, status="failed")

    return {
        "team_id": team_id,
        "task": team["task"],
        "status": team_status,
        "backend": team["backend"],
        "agents": agent_summaries,
        "artifacts_count": sum(1 for a in agents if a["artifact_status"]),
    }


def stop_team(db: Database, team_id: str) -> dict[str, Any]:
    """Stop all agents in a team. Data preserved for resume."""
    agents = db.list_agents(team_id=team_id)
    killed = 0

    for agent in agents:
        if agent["tmux_session"] and session_exists(agent["tmux_session"]):
            kill_session(agent["tmux_session"])
            killed += 1
        release_agent_locks(db, agent["id"])
        db.update_agent(agent["id"], status="dead")

    db.update_team(team_id, status="dead")
    db.insert_event("team_stopped", team_id=team_id, payload={"killed": killed})

    return {"team_id": team_id, "status": "dead", "agents_killed": killed}


def get_team_result(db: Database, team_id: str) -> dict[str, Any] | None:
    """Read the team lead's consolidated artifact."""
    result = read_team_result(team_id)
    if result:
        return result.model_dump()

    artifacts = list_artifacts(team_id)
    if artifacts:
        return {
            "status": "partial",
            "artifacts": [a.model_dump() for a in artifacts],
        }
    return None
