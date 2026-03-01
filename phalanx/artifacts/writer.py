"""Atomic artifact writer — used by agents via `phalanx write-artifact`."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .schema import Artifact, ArtifactStatus


TEAMS_DIR = Path.home() / ".phalanx" / "teams"


def get_artifact_path(team_id: str, agent_id: str) -> Path:
    return TEAMS_DIR / team_id / "agents" / agent_id / "artifact.json"


def get_stream_log_path(team_id: str, agent_id: str) -> Path:
    return TEAMS_DIR / team_id / "agents" / agent_id / "stream.log"


def write_artifact(
    status: str,
    output: dict[str, Any],
    team_id: str | None = None,
    agent_id: str | None = None,
    warnings: list[str] | None = None,
) -> Artifact:
    """Validate and atomically write an artifact to disk.

    Reads PHALANX_TEAM_ID and PHALANX_AGENT_ID from env if not provided.
    """
    team_id = team_id or os.environ.get("PHALANX_TEAM_ID", "")
    agent_id = agent_id or os.environ.get("PHALANX_AGENT_ID", "")

    if not team_id or not agent_id:
        raise ValueError("team_id and agent_id are required (set env or pass explicitly)")

    artifact = Artifact(
        status=ArtifactStatus(status),
        agent_id=agent_id,
        team_id=team_id,
        output=output,
        warnings=warnings or [],
    )

    path = get_artifact_path(team_id, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temp file then rename
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(artifact.model_dump_json(indent=2))
        os.replace(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return artifact
