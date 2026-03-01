"""Team creation: parse agent spec, spawn workers + lead."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from phalanx.backends import get_backend, resolve_model
from phalanx.config import load_config
from phalanx.db import Database
from phalanx.monitor.gc import gc_check
from .spawn import spawn_worker, spawn_team_lead


def parse_agents_spec(spec: str) -> list[tuple[str, int]]:
    """Parse agent spec like 'researcher,coder:2,reviewer' into [(role, count)]."""
    agents = []
    for part in spec.split(","):
        part = part.strip()
        if ":" in part:
            role, count_str = part.split(":", 1)
            agents.append((role.strip(), int(count_str)))
        else:
            agents.append((part, 1))
    return agents


def create_team(
    db: Database,
    task: str,
    agents_spec: str = "coder",
    backend_name: str | None = None,
    model: str | None = None,
    workspace: Path | None = None,
    use_worktree: bool = False,
    config: dict[str, Any] | None = None,
) -> dict:
    """Create a team: spawn all workers, then spawn team lead.

    Returns dict with team info and agent IDs.
    """
    config = config or load_config(workspace)

    if backend_name is None:
        backend_name = config.get("defaults", {}).get("backend", "")
        if not backend_name:
            from phalanx.backends.registry import detect_default
            backend_name = detect_default()

    backend = get_backend(backend_name)
    workspace = workspace or Path.cwd()
    team_id = uuid.uuid4().hex[:12]

    # Opportunistic GC
    gc_hours = config.get("timeouts", {}).get("team_gc_hours", 24)
    gc_check(db, gc_hours=gc_hours)

    # Create team in DB
    db.create_team(team_id, task, backend_name, model=model)

    # Parse and spawn workers
    agent_specs = parse_agents_spec(agents_spec)
    worker_ids = []
    worker_index = 0

    for role, count in agent_specs:
        for i in range(count):
            worktree_name = f"{team_id}-worker-{worker_index}" if use_worktree else None
            agent = spawn_worker(
                db=db,
                backend=backend,
                team_id=team_id,
                task=task,
                role=role,
                config=config,
                workspace=workspace,
                index=worker_index,
                worktree=worktree_name,
            )
            worker_ids.append(agent["id"])
            worker_index += 1

    # Spawn team lead
    lead = spawn_team_lead(
        db=db,
        backend=backend,
        team_id=team_id,
        team_task=task,
        worker_ids=worker_ids,
        config=config,
        workspace=workspace,
    )

    db.insert_event("team_created", team_id=team_id,
                    payload={"workers": worker_ids, "lead": lead["id"]})

    return {
        "team_id": team_id,
        "task": task,
        "backend": backend_name,
        "workers": worker_ids,
        "lead": lead["id"],
        "status": "running",
    }
