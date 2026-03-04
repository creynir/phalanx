"""Team creation and management."""

from __future__ import annotations

import logging
import shlex
import uuid
from pathlib import Path

import libtmux

from phalanx.config import PhalanxConfig
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.process.manager import ProcessManager
from phalanx.team.config import TeamConfig, resolve_model
from phalanx.team.spawn import spawn_agent

logger = logging.getLogger(__name__)


def _create_agent_worktree(repo_path: Path, team_id: str, agent_id: str) -> Path | None:
    """Create a git worktree for an agent. Returns the path or None on failure."""
    from phalanx.process.worktree import create_worktree

    name = f"{team_id}-{agent_id}"
    try:
        wt_path = create_worktree(repo_path, name)
        logger.info("Created worktree for agent %s at %s", agent_id, wt_path)
        return wt_path
    except Exception as e:
        logger.warning("Failed to create worktree for agent %s: %s", agent_id, e)
        return None


def parse_agents_spec(spec: str) -> list[tuple[str, int]]:
    """Parse agent spec like 'researcher,coder:2,reviewer' into [(role, count)]."""
    agents = []
    if not spec:
        return agents
    for part in spec.split(","):
        part = part.strip()
        if ":" in part:
            role, count_str = part.split(":", 1)
            agents.append((role.strip(), int(count_str)))
        else:
            agents.append((part, 1))
    return agents


def create_team_from_config(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    team_config: TeamConfig,
    backend_name: str = "cursor",
    auto_approve: bool = False,
    config: PhalanxConfig | None = None,
    idle_timeout: int = 1800,
    max_runtime: int = 1800,
) -> tuple[str, str, list[str]]:
    """Create a team from a full config with per-agent prompts.

    Returns (team_id, lead_agent_id, [worker_agent_ids]).
    """
    team_id = f"team-{uuid.uuid4().hex[:8]}"

    team_config.generate_ids()

    db.create_team(team_id, team_config.task, config=team_config.to_dict())

    team_dir = phalanx_root / "teams" / team_id
    team_dir.mkdir(parents=True, exist_ok=True)
    team_config.save(team_dir / "config.json")

    worker_ids = []
    for agent_spec in team_config.agents:
        model = agent_spec.resolve_model(backend_name)

        spawn_agent(
            phalanx_root=phalanx_root,
            db=db,
            process_manager=process_manager,
            heartbeat_monitor=heartbeat_monitor,
            team_id=team_id,
            task=agent_spec.prompt,
            role=agent_spec.role,
            agent_id=agent_spec.agent_id,
            backend_name=backend_name,
            model=model,
            worktree=agent_spec.worktree,
            working_dir=agent_spec.worktree,
            auto_approve=auto_approve,
            config=config,
        )
        worker_ids.append(agent_spec.agent_id)

    lead_model = team_config.lead.resolve_model(backend_name)
    lead_id = team_config.lead.agent_id

    worker_list = "\n".join(
        f"- {a.agent_id} (role={a.role}, name={a.name})" for a in team_config.agents
    )
    lead_task = f"Team task: {team_config.task}\n\nWorkers:\n{worker_list}\n\nTeam ID: {team_id}"

    spawn_agent(
        phalanx_root=phalanx_root,
        db=db,
        process_manager=process_manager,
        heartbeat_monitor=heartbeat_monitor,
        team_id=team_id,
        task=lead_task,
        role="lead",
        agent_id=lead_id,
        backend_name=backend_name,
        model=lead_model,
        auto_approve=auto_approve,
        config=config,
    )

    _spawn_team_monitor(phalanx_root, team_id, idle_timeout=idle_timeout, max_runtime=max_runtime)

    logger.info(
        "Created team %s with lead %s and %d workers",
        team_id,
        lead_id,
        len(worker_ids),
    )
    return team_id, lead_id, worker_ids


def create_team(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    task: str,
    agents_spec: str = "coder",
    backend_name: str = "cursor",
    model: str | None = None,
    auto_approve: bool = False,
    config: PhalanxConfig | None = None,
    idle_timeout: int = 1800,
    max_runtime: int = 1800,
    worktree: bool = False,
) -> tuple[str, str]:
    """Create a team using the simple --task + --agents spec.

    All workers get the same task. Returns (team_id, lead_agent_id).
    """
    team_id = f"team-{uuid.uuid4().hex[:8]}"
    lead_id = f"lead-{uuid.uuid4().hex[:8]}"

    team_config_data = {}
    if config:
        team_config_data = config.to_dict()
    db.create_team(team_id, task, config=team_config_data)

    team_dir = phalanx_root / "teams" / team_id
    team_dir.mkdir(parents=True, exist_ok=True)

    repo_path = phalanx_root.parent if phalanx_root.name == ".phalanx" else Path.cwd()

    worker_specs = parse_agents_spec(agents_spec)
    worker_index = 0
    for role, count in worker_specs:
        for _ in range(count):
            worker_id = f"w{worker_index}-{role}-{uuid.uuid4().hex[:8]}"
            resolved_model = resolve_model(backend_name, role, model)
            worker_worktree: str | None = None
            worker_working_dir: str | None = None
            if worktree:
                wt_path = _create_agent_worktree(repo_path, team_id, worker_id)
                if wt_path is not None:
                    worker_worktree = str(wt_path)
                    worker_working_dir = str(wt_path)
            spawn_agent(
                phalanx_root=phalanx_root,
                db=db,
                process_manager=process_manager,
                heartbeat_monitor=heartbeat_monitor,
                team_id=team_id,
                task=task,
                role=role,
                agent_id=worker_id,
                backend_name=backend_name,
                model=resolved_model,
                auto_approve=auto_approve,
                config=config,
                worktree=worker_worktree,
                working_dir=worker_working_dir,
            )
            worker_index += 1

    lead_model = resolve_model(backend_name, "lead", model)
    lead_worktree: str | None = None
    lead_working_dir: str | None = None
    if worktree:
        wt_path = _create_agent_worktree(repo_path, team_id, lead_id)
        if wt_path is not None:
            lead_worktree = str(wt_path)
            lead_working_dir = str(wt_path)
    spawn_agent(
        phalanx_root=phalanx_root,
        db=db,
        process_manager=process_manager,
        heartbeat_monitor=heartbeat_monitor,
        team_id=team_id,
        task=task,
        role="lead",
        agent_id=lead_id,
        backend_name=backend_name,
        model=lead_model,
        auto_approve=auto_approve,
        config=config,
        worktree=lead_worktree,
        working_dir=lead_working_dir,
    )

    _spawn_team_monitor(phalanx_root, team_id, idle_timeout=idle_timeout, max_runtime=max_runtime)

    logger.info("Created team %s with lead %s", team_id, lead_id)
    return team_id, lead_id


def _spawn_team_monitor(
    phalanx_root: Path,
    team_id: str,
    idle_timeout: int | None = None,
    max_runtime: int | None = None,
) -> None:
    """Spawn the team-monitor daemon in its own tmux session."""
    import sys

    session_name = f"phalanx-mon-{team_id}"
    python = shlex.quote(sys.executable)
    cmd = f"{python} -m phalanx.cli --root {shlex.quote(str(phalanx_root))} team-monitor {team_id}"
    if idle_timeout is not None:
        cmd += f" --idle-timeout {idle_timeout}"
    if max_runtime is not None:
        cmd += f" --max-runtime {max_runtime}"

    try:
        server = libtmux.Server()
        try:
            existing = server.sessions.get(session_name=session_name)
            existing.kill()
        except Exception:
            pass

        session = server.new_session(session_name=session_name)
        pane = session.active_window.active_pane
        pane.send_keys(cmd, enter=True)
        logger.info("Spawned team monitor in tmux session %s", session_name)
    except Exception as e:
        logger.warning("Failed to spawn team monitor for %s: %s", team_id, e)
