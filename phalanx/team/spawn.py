"""Agent spawning with soul file injection and environment setup.

Handles both team-based spawning (from team lead) and single-agent mode
(from `phalanx create-team`). Agents always run in TUI mode
inside tmux with pipe-pane log streaming.
"""

from __future__ import annotations

import logging
import os
import time
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
    backend_name: str = "codex",
    model: str | None = None,
    worktree: str | None = None,
    working_dir: str | None = None,
    auto_approve: bool = False,
    config: PhalanxConfig | None = None,
) -> AgentProcess:
    """Spawn an agent in TUI mode with full setup.

    1. Generate agent ID
    2. Create git worktree (if --worktree flag was set)
    3. Load and inject soul file
    4. Write task file for long prompts
    5. Create DB record
    6. Spawn tmux session with pipe-pane
    7. Register heartbeat monitor
    """
    if agent_id is None:
        agent_id = f"{role}-{uuid.uuid4().hex[:8]}"

    backend = get_backend(backend_name)

    effective_worktree: str | None = worktree
    effective_working_dir: str | None = working_dir

    soul_file = _resolve_soul_file(phalanx_root, role)

    task_file = _write_task_file(phalanx_root, team_id, agent_id, task, soul_file=soul_file)

    try:
        agent_proc = process_manager.spawn(
            team_id=team_id,
            agent_id=agent_id,
            backend=backend,
            prompt=str(task_file),
            soul_file=None,
            model=model,
            worktree=effective_worktree,
            working_dir=effective_working_dir,
            auto_approve=auto_approve,
        )
    except Exception:
        logger.error("Failed to spawn agent %s", agent_id)
        raise

    # Normalize v1 role strings to v2 DB values: only "lead" and "agent" are valid.
    db_role = role if role in ("lead", "agent") else "agent"
    db.create_agent(
        agent_id=agent_id,
        team_id=team_id,
        task=task,
        role=db_role,
        model=model,
        backend=backend_name,
        worktree=effective_worktree,
    )

    db.update_agent(agent_id, status="running", pid=os.getpid())
    db.log_event(team_id, "spawn", agent_id=agent_id, payload={"task": task[:200], "model": model})

    heartbeat_monitor.register(agent_id, agent_proc.stream_log)

    # Stagger spawns to avoid backend-specific filesystem races (e.g. Cursor
    # agents racing to rewrite cli-config.json on startup).
    delay = backend.spawn_delay()
    if delay > 0:
        logger.debug(
            "Staggering next spawn by %.1fs (backend=%s)",
            delay,
            backend_name,
        )
        time.sleep(delay)

    logger.info(
        "Spawned agent %s (role=%s, backend=%s, model=%s) in team %s",
        agent_id,
        role,
        backend_name,
        model or "default",
        team_id,
    )
    return agent_proc


def _write_task_file(
    phalanx_root: Path,
    team_id: str,
    agent_id: str,
    task: str,
    soul_file: Path | None = None,
) -> Path:
    """Write a single merged prompt file combining soul + task.

    Merging into one file ensures the agent receives a single imperative
    message rather than two @file references it will summarise and await
    follow-up on. The soul preamble is prepended so the agent has its role
    context before reading the task.

    Substitutes:
      {task} — the agent's assigned task text
    """
    agent_dir = phalanx_root / "teams" / team_id / "agents" / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    task_file = agent_dir / "task.md"

    if soul_file and soul_file.exists():
        soul_content = soul_file.read_text(encoding="utf-8")
        if "{task}" in soul_content:
            merged = soul_content.replace("{task}", task)
        else:
            merged = f"{soul_content}\n\n---\n\n{task}"
        # Prepend a hard imperative so the very first token the agent sees is
        # an action verb, not a document to read and summarise.
        merged = (
            "Execute the following task immediately "
            "without summarising or asking questions:"
            f"\n\n{merged}"
        )
    else:
        merged = task

    task_file.write_text(merged, encoding="utf-8")
    return task_file


_SOUL_FILE_MAP = {
    "lead": "team_lead.md",
    "engineering_manager": "engineering_manager.md",
}


def _resolve_soul_file(phalanx_root: Path, role: str) -> Path | None:
    """Find the appropriate soul file for the role."""
    if role not in _SOUL_FILE_MAP and role != "worker":
        import logging

        logging.getLogger(__name__).warning(
            "No specific soul file for role '%s', falling back to worker.md", role
        )
    filename = _SOUL_FILE_MAP.get(role, "worker.md")

    soul_dir = phalanx_root / "soul"
    path = soul_dir / filename
    if path.exists():
        return path

    bundled = Path(__file__).parent.parent / "soul"
    bundled_path = bundled / filename
    if bundled_path.exists():
        return bundled_path

    return None
