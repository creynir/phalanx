"""Team orchestration: status, stop, resume, result reading."""

from __future__ import annotations

import logging
from pathlib import Path

from phalanx.artifacts.reader import read_agent_artifact, read_team_artifact
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
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
    """Stop all agents in a team and the team monitor. Data is preserved for resuming."""
    agents = db.list_agents(team_id)
    stopped = []
    for agent in agents:
        if agent["status"] in ("running", "pending", "blocked_on_prompt"):
            process_manager.kill_agent(agent["id"])
            db.update_agent(agent["id"], status="dead")
            stopped.append(agent["id"])

    _kill_team_monitor(team_id)

    db.update_team_status(team_id, "dead")
    logger.info("Stopped team %s (%d agents killed)", team_id, len(stopped))
    return {"team_id": team_id, "stopped_agents": stopped}


def resume_team(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    team_id: str,
    resume_all: bool = False,
    auto_approve: bool = False,
) -> dict:
    """Resume a dead/stopped team by restarting agents.

    By default only restarts the team lead. With resume_all=True,
    restarts all dead agents.
    """
    from phalanx.backends import get_backend
    from phalanx.team.create import _spawn_team_monitor

    agents = db.list_agents(team_id)
    resumed = []

    for agent in agents:
        if agent["status"] not in ("dead", "suspended"):
            continue

        is_lead = agent["role"] == "lead"
        if not is_lead and not resume_all:
            continue

        agent_id = agent["id"]
        backend = get_backend(agent.get("backend", "cursor"))
        chat_id = agent.get("chat_id")

        if chat_id:
            agent_proc = process_manager.spawn_resume(
                team_id=team_id,
                agent_id=agent_id,
                backend=backend,
                chat_id=chat_id,
                auto_approve=auto_approve,
            )
        else:
            task_file = phalanx_root / "teams" / team_id / "agents" / agent_id / "task.md"
            soul_dir = Path(__file__).parent.parent / "soul"
            soul_file = soul_dir / ("team_lead.md" if is_lead else "worker.md")
            if not soul_file.exists():
                soul_file = None

            if not task_file.exists():
                raw_task = agent.get("task", "")
                if not raw_task:
                    logger.warning(
                        "Cannot resume agent %s: no chat_id, no task.md, no task in DB",
                        agent_id,
                    )
                    continue
                task_file.parent.mkdir(parents=True, exist_ok=True)
                task_file.write_text(raw_task, encoding="utf-8")

            agent_proc = process_manager.spawn(
                team_id=team_id,
                agent_id=agent_id,
                backend=backend,
                prompt=str(task_file),
                soul_file=soul_file,
                model=agent.get("model"),
                auto_approve=auto_approve,
            )

        db.update_agent(agent_id, status="running")
        heartbeat_monitor.register(agent_id, agent_proc.stream_log)
        resumed.append(agent_id)

        logger.info("Resumed agent %s in team %s", agent_id, team_id)

    if resumed:
        db.update_team_status(team_id, "running")
        _spawn_team_monitor(phalanx_root, team_id)

    return {"team_id": team_id, "resumed_agents": resumed}


def resume_single_agent(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    agent_id: str,
    auto_approve: bool = False,
) -> dict:
    """Resume a single dead/suspended agent within its team."""
    from phalanx.backends import get_backend

    agent = db.get_agent(agent_id)
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found")

    if agent["status"] not in ("dead", "suspended"):
        raise ValueError(f"Agent {agent_id} is {agent['status']}, not dead/suspended")

    team_id = agent["team_id"]
    is_lead = agent["role"] == "lead"
    backend = get_backend(agent.get("backend", "cursor"))
    chat_id = agent.get("chat_id")

    if chat_id:
        agent_proc = process_manager.spawn_resume(
            team_id=team_id,
            agent_id=agent_id,
            backend=backend,
            chat_id=chat_id,
            auto_approve=auto_approve,
        )
    else:
        task_file = phalanx_root / "teams" / team_id / "agents" / agent_id / "task.md"
        soul_dir = Path(__file__).parent.parent / "soul"
        soul_file = soul_dir / ("team_lead.md" if is_lead else "worker.md")
        if not soul_file.exists():
            soul_file = None

        if not task_file.exists():
            raw_task = agent.get("task", "")
            if not raw_task:
                raise ValueError(
                    f"Cannot resume agent {agent_id}: no chat_id, no task.md, no task in DB"
                )
            task_file.parent.mkdir(parents=True, exist_ok=True)
            task_file.write_text(raw_task, encoding="utf-8")

        agent_proc = process_manager.spawn(
            team_id=team_id,
            agent_id=agent_id,
            backend=backend,
            prompt=str(task_file),
            soul_file=soul_file,
            model=agent.get("model"),
            auto_approve=auto_approve,
        )

    db.update_agent(agent_id, status="running")
    heartbeat_monitor.register(agent_id, agent_proc.stream_log)
    logger.info("Resumed agent %s in team %s", agent_id, team_id)

    return {"agent_id": agent_id, "team_id": team_id, "status": "running"}


def _kill_team_monitor(team_id: str) -> None:
    """Kill the team monitor tmux session if it exists."""
    try:
        import libtmux

        server = libtmux.Server()
        session_name = f"phalanx-mon-{team_id}"
        session = server.sessions.get(session_name=session_name)
        session.kill()
        logger.info("Killed team monitor session %s", session_name)
    except Exception:
        pass


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
