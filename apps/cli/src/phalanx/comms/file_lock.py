"""Advisory file locking via SQLite.

Application-level locks tracked in the file_locks table. Auto-cleaned
when agents die (PID check) or when teams are stopped.
"""

from __future__ import annotations

import logging
import os

from phalanx.db import StateDB

logger = logging.getLogger(__name__)


def acquire_lock(
    db: StateDB,
    file_path: str,
    team_id: str,
    agent_id: str,
    pid: int | None = None,
) -> bool:
    """Acquire an advisory lock on a file path."""
    if pid is None:
        pid = os.getpid()

    # Try to acquire
    if db.acquire_lock(file_path, team_id, agent_id, pid):
        logger.debug("Lock acquired: %s by %s", file_path, agent_id)
        return True

    # Check if the holder is dead
    locks = db.list_locks()
    for lock in locks:
        if lock["file_path"] == file_path:
            holder_pid = lock["pid"]
            if not _pid_alive(holder_pid):
                logger.info(
                    "Releasing stale lock on %s (holder pid %d is dead)",
                    file_path,
                    holder_pid,
                )
                db.release_lock(file_path)
                return db.acquire_lock(file_path, team_id, agent_id, pid)
            break

    logger.debug("Lock denied: %s (held by another agent)", file_path)
    return False


def release_lock(db: StateDB, file_path: str) -> None:
    """Release an advisory lock."""
    db.release_lock(file_path)
    logger.debug("Lock released: %s", file_path)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
