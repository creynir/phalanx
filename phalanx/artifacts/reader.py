"""Read artifacts written by agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import Artifact
from .writer import get_artifact_path, TEAMS_DIR


def read_artifact(team_id: str, agent_id: str) -> Artifact | None:
    """Read and validate an agent's artifact. Returns None if not found."""
    path = get_artifact_path(team_id, agent_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Artifact(**data)


def read_team_result(team_id: str) -> Artifact | None:
    """Read the team lead's artifact (the consolidated team result)."""
    team_dir = TEAMS_DIR / team_id / "agents"
    if not team_dir.exists():
        return None

    for agent_dir in team_dir.iterdir():
        artifact_path = agent_dir / "artifact.json"
        if artifact_path.exists():
            data = json.loads(artifact_path.read_text())
            if data.get("agent_id", "").startswith("lead"):
                return Artifact(**data)
    return None


def list_artifacts(team_id: str) -> list[Artifact]:
    """List all artifacts for a team."""
    team_dir = TEAMS_DIR / team_id / "agents"
    if not team_dir.exists():
        return []

    artifacts = []
    for agent_dir in sorted(team_dir.iterdir()):
        artifact_path = agent_dir / "artifact.json"
        if artifact_path.exists():
            data = json.loads(artifact_path.read_text())
            artifacts.append(Artifact(**data))
    return artifacts
