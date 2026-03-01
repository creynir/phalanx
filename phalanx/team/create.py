"""Team creation and management."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from phalanx.config import PhalanxConfig
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.process.manager import ProcessManager
from phalanx.team.spawn import spawn_agent

logger = logging.getLogger(__name__)


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


def create_team(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    task: str,
    agents_spec: str = "coder",
    backend_name: str = "cursor",
    model: str | None = None,
    auto_approve: bool = True,
    config: PhalanxConfig | None = None,
) -> tuple[str, str]:
    """Create a new team and spawn its team lead.

    Returns (team_id, lead_agent_id).
    """
    team_id = f"team-{uuid.uuid4().hex[:8]}"
    lead_id = f"lead-{uuid.uuid4().hex[:8]}"

    # Create team in DB
    team_config = {}
    if config:
        team_config = config.to_dict()
    db.create_team(team_id, task, config=team_config)

    # Create team directory
    team_dir = phalanx_root / "teams" / team_id
    team_dir.mkdir(parents=True, exist_ok=True)

    # Spawn workers first
    worker_specs = parse_agents_spec(agents_spec)
    worker_index = 0
    for role, count in worker_specs:
        for _ in range(count):
            worker_id = f"w{worker_index}-{role}"
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
                model=None,  # let router decide based on role
                auto_approve=auto_approve,
                config=config,
            )
            worker_index += 1

    # Spawn team lead
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
        model=model,
        auto_approve=auto_approve,
        config=config,
    )

    logger.info("Created team %s with lead %s", team_id, lead_id)
    return team_id, lead_id
