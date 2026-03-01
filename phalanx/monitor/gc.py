"""Opportunistic garbage collection.

Runs as a side-effect of any phalanx command. Deletes teams that have been
dead for longer than the configured GC threshold (default 24 hours).
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_GC_HOURS = 24


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
