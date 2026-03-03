"""Opportunistic garbage collection.

Runs as a side-effect of any phalanx command. Deletes teams that have been
dead for longer than the configured GC threshold (default 24 hours).
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from phalanx.process.worktree import WORKTREE_BASE

logger = logging.getLogger(__name__)

DEFAULT_GC_HOURS = 24


def _kill_monitor_session(team_id: str) -> None:
    """Kill the team monitor tmux session if it exists."""
    try:
        import libtmux

        server = libtmux.Server()
        session_name = f"phalanx-mon-{team_id}"
        session = server.sessions.get(session_name=session_name)
        session.kill()
        logger.info("GC: killed monitor session %s", session_name)
    except Exception:
        pass


def _cleanup_worktrees(team_id: str) -> None:
    """Remove all git worktree directories associated with a dead team.

    Iterates WORKTREE_BASE/<repo>/ and removes directories whose name starts
    with the team_id. Uses shutil.rmtree rather than `git worktree remove`
    because the original repo path is unavailable during GC.
    """
    if not WORKTREE_BASE.exists():
        return
    for repo_dir in WORKTREE_BASE.iterdir():
        if not repo_dir.is_dir():
            continue
        for wt_dir in repo_dir.iterdir():
            if wt_dir.is_dir() and wt_dir.name.startswith(team_id):
                try:
                    shutil.rmtree(wt_dir, ignore_errors=True)
                    logger.info("GC: removed worktree %s", wt_dir)
                except Exception:
                    logger.debug("GC: failed to remove worktree %s", wt_dir)


def run_gc(
    phalanx_root: Path,
    db=None,
    max_age_hours: int = DEFAULT_GC_HOURS,
) -> list[str]:
    """Delete dead teams older than max_age_hours.

    Returns list of deleted team IDs.
    """
    if db is None:
        return []

    cutoff = time.time() - (max_age_hours * 3600)
    deleted = []

    try:
        dead_teams = db.get_dead_teams_before(cutoff)
    except Exception as e:
        logger.debug("GC query failed: %s", e)
        return []

    for team_id in dead_teams:
        _kill_monitor_session(team_id)
        _cleanup_worktrees(team_id)

        team_dir = phalanx_root / "teams" / team_id
        if team_dir.exists():
            shutil.rmtree(team_dir, ignore_errors=True)
            logger.info("GC: deleted team directory %s", team_dir)

        try:
            db.delete_team(team_id)
        except Exception as e:
            logger.warning("GC: failed to delete team %s from DB: %s", team_id, e)
            continue

        deleted.append(team_id)

    if deleted:
        logger.info("GC: cleaned up %d dead teams", len(deleted))

    return deleted
