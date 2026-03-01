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


def create_team(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    task: str,
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
