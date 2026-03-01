"""Read agent and team artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from phalanx.artifacts.schema import Artifact


def read_artifact(artifact_dir: Path) -> Artifact | None:
    """Read an artifact from a directory."""
    path = artifact_dir / "artifact.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Artifact.from_dict(data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def read_agent_artifact(
    phalanx_root: Path,
    team_id: str,
    agent_id: str,
) -> Artifact | None:
    """Read a specific agent's artifact."""
    agent_dir = phalanx_root / "teams" / team_id / "agents" / agent_id
    return read_artifact(agent_dir)


def read_team_artifact(
    phalanx_root: Path,
    team_id: str,
) -> Artifact | None:
    """Read the team lead's artifact."""
    lead_dir = phalanx_root / "teams" / team_id / "lead"
    return read_artifact(lead_dir)
