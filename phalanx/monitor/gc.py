"""Opportunistic garbage collection — runs as side effect of any phalanx command."""

from __future__ import annotations

import shutil
from pathlib import Path

from phalanx.db import Database
from phalanx.artifacts.writer import TEAMS_DIR
from phalanx.comms.file_lock import cleanup_dead_locks


def gc_check(db: Database, gc_hours: int = 24, teams_dir: Path | None = None) -> int:
    """Check for and clean up stale teams. Returns number of teams cleaned."""
    teams_dir = teams_dir or TEAMS_DIR
    stale = db.get_stale_teams(gc_hours=gc_hours)
    cleaned = 0

    for team in stale:
        cleanup_team(db, team["id"], teams_dir)
        cleaned += 1

    cleanup_dead_locks(db)
    return cleaned


def cleanup_team(db: Database, team_id: str, teams_dir: Path | None = None) -> None:
    """Full cleanup: delete team directory, SQLite rows, worktrees."""
    teams_dir = teams_dir or TEAMS_DIR
    team_dir = teams_dir / team_id

    if team_dir.exists():
        shutil.rmtree(team_dir)

    db.insert_event("team_gc", team_id=team_id, payload={"reason": "24h_inactivity"})
    db.delete_team(team_id)
