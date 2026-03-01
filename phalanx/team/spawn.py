"""Agent spawning with soul file injection and env setup."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from phalanx.backends.base import AgentBackend
from phalanx.backends.model_router import resolve_model
from phalanx.db import Database
from phalanx.process.manager import spawn_in_tmux
from phalanx.artifacts.writer import get_stream_log_path, TEAMS_DIR
from phalanx.soul.loader import (
    load_team_lead_soul,
    load_worker_soul,
    write_soul_to_temp,
)


def _make_agent_id(role: str, index: int | None = None) -> str:
    short = uuid.uuid4().hex[:6]
    if index is not None:
        return f"{role}-{index}-{short}"
    return f"{role}-{short}"


def spawn_worker(
    db: Database,
    backend: AgentBackend,
    team_id: str,
    task: str,
    role: str,
    config: dict[str, Any],
    workspace: Path,
    index: int | None = None,
    worktree: str | None = None,
) -> dict:
    """Spawn a single worker agent in tmux."""
    agent_id = _make_agent_id(role, index)
    model = resolve_model(backend.name, role, config)

    team_dir = TEAMS_DIR / team_id
    soul_content = load_worker_soul(task=task)
    soul_path = write_soul_to_temp(soul_content, team_dir, agent_id)

    cmd = backend.build_headless_command(
        prompt=soul_content + "\n\n" + task,
        workspace=workspace,
        model=model,
        worktree=worktree,
        soul_file=soul_path,
        auto_approve=True,
    )

    stream_log = get_stream_log_path(team_id, agent_id)
    env = {
        "PHALANX_TEAM_ID": team_id,
        "PHALANX_AGENT_ID": agent_id,
    }

    result = spawn_in_tmux(
        cmd=cmd,
        team_id=team_id,
        agent_id=agent_id,
        stream_log=stream_log,
        working_dir=workspace,
        env=env,
    )

    db.create_agent(
        agent_id=agent_id,
        team_id=team_id,
        role=role,
        task=task,
        backend=backend.name,
        model=model,
        tmux_session=result["session_name"],
        pid=result["pane_pid"],
        status="running",
    )

    db.insert_event("agent_spawned", team_id=team_id, agent_id=agent_id,
                    payload={"role": role, "model": model})

    return db.get_agent(agent_id)


def spawn_team_lead(
    db: Database,
    backend: AgentBackend,
    team_id: str,
    team_task: str,
    worker_ids: list[str],
    config: dict[str, Any],
    workspace: Path,
) -> dict:
    """Spawn the team lead agent."""
    agent_id = _make_agent_id("lead")
    model = resolve_model(backend.name, "orchestrator", config)

    worker_list = "\n".join(f"- {wid}" for wid in worker_ids)
    soul_content = load_team_lead_soul(worker_list=worker_list, team_task=team_task)

    team_dir = TEAMS_DIR / team_id
    soul_path = write_soul_to_temp(soul_content, team_dir, agent_id)

    cmd = backend.build_headless_command(
        prompt=soul_content,
        workspace=workspace,
        model=model,
        soul_file=soul_path,
        auto_approve=True,
    )

    stream_log = get_stream_log_path(team_id, agent_id)
    env = {
        "PHALANX_TEAM_ID": team_id,
        "PHALANX_AGENT_ID": agent_id,
    }

    result = spawn_in_tmux(
        cmd=cmd,
        team_id=team_id,
        agent_id=agent_id,
        stream_log=stream_log,
        working_dir=workspace,
        env=env,
    )

    db.create_agent(
        agent_id=agent_id,
        team_id=team_id,
        role="lead",
        task=team_task,
        backend=backend.name,
        model=model,
        tmux_session=result["session_name"],
        pid=result["pane_pid"],
        status="running",
    )

    db.insert_event("lead_spawned", team_id=team_id, agent_id=agent_id,
                    payload={"model": model, "worker_count": len(worker_ids)})

    return db.get_agent(agent_id)
