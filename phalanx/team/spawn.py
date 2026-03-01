"""Agent spawning with soul file injection and environment setup.

Handles both team-based spawning (from team lead) and single-agent mode
(from `phalanx run-agent`). In both cases, agents run in TUI mode
inside tmux with pipe-pane log streaming.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from phalanx.backends import get_backend
from phalanx.config import PhalanxConfig
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.process.manager import AgentProcess, ProcessManager

logger = logging.getLogger(__name__)


def spawn_agent(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    team_id: str,
    task: str,
    role: str = "worker",
    agent_id: str | None = None,
    backend_name: str = "cursor",
    model: str | None = None,
    worktree: str | None = None,
    working_dir: str | None = None,
    auto_approve: bool = True,
    config: PhalanxConfig | None = None,
) -> AgentProcess:
    """Spawn an agent in TUI mode with full setup.

    1. Generate agent ID
    2. Load and inject soul file
    3. Create DB record
    4. Spawn tmux session with pipe-pane
    5. Register heartbeat monitor
    """
    if agent_id is None:
        agent_id = f"{role}-{uuid.uuid4().hex[:8]}"

    backend = get_backend(backend_name)

    # Load appropriate soul file
    soul_file = _resolve_soul_file(phalanx_root, role)

    # Create DB record
    db.create_agent(
        agent_id=agent_id,
        team_id=team_id,
        task=task,
        role=role,
        model=model,
        backend=backend_name,
        worktree=worktree,
    )

    # Set environment variables for the agent
    env_vars = {
        "PHALANX_AGENT_ID": agent_id,
        "PHALANX_TEAM_ID": team_id,
        "PHALANX_ROOT": str(phalanx_root),
    }
    for k, v in env_vars.items():
        os.environ[k] = v

    # Spawn in tmux
    agent_proc = process_manager.spawn(
        team_id=team_id,
        agent_id=agent_id,
        backend=backend,
        prompt=task,
        soul_file=soul_file,
        model=model,
        worktree=worktree,
        working_dir=working_dir,
        auto_approve=auto_approve,
    )

    # Update DB with running state
    db.update_agent(agent_id, status="running", pid=os.getpid())
    db.log_event(team_id, "spawn", agent_id=agent_id, payload={"task": task, "model": model})

    # Register heartbeat
    heartbeat_monitor.register(agent_id, agent_proc.stream_log)

    logger.info(
        "Spawned agent %s (role=%s, backend=%s, model=%s) in team %s",
        agent_id,
        role,
        backend_name,
        model or "default",
        team_id,
    )
    return agent_proc


def spawn_single_agent(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    task: str,
    backend_name: str = "cursor",
    model: str | None = None,
    auto_approve: bool = True,
    config: PhalanxConfig | None = None,
) -> tuple[str, str, AgentProcess]:
    """Spawn a single agent without a team lead (run-agent mode).

    Creates a synthetic team with a single worker. Returns
    (team_id, agent_id, AgentProcess).
    """
    team_id = f"solo-{uuid.uuid4().hex[:8]}"
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"

    # Create a synthetic team
    db.create_team(team_id, task, config={"mode": "single-agent"})

    agent_proc = spawn_agent(
        phalanx_root=phalanx_root,
        db=db,
        process_manager=process_manager,
        heartbeat_monitor=heartbeat_monitor,
        team_id=team_id,
        task=task,
        role="worker",
        agent_id=agent_id,
        backend_name=backend_name,
        model=model,
        auto_approve=auto_approve,
        config=config,
    )

    logger.info("Single-agent mode: team=%s, agent=%s", team_id, agent_id)
    return team_id, agent_id, agent_proc


def _resolve_soul_file(phalanx_root: Path, role: str) -> Path | None:
    """Find the appropriate soul file for the role."""
    soul_dir = phalanx_root / "soul"
    if role == "lead":
        path = soul_dir / "team_lead.md"
    else:
        path = soul_dir / "worker.md"

    if path.exists():
        return path

    # Try bundled soul files
    bundled = Path(__file__).parent.parent / "soul"
    if role == "lead":
        bundled_path = bundled / "team_lead.md"
    else:
        bundled_path = bundled / "worker.md"

    if bundled_path.exists():
        return bundled_path

    return None
