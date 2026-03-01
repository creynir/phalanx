"""Advisory file locking via SQLite — agents lock files before editing."""

from __future__ import annotations

import os

from phalanx.db import Database


def acquire_lock(db: Database, file_path: str, team_id: str, agent_id: str) -> bool:
    """Try to lock a file. Returns True if acquired, False if already locked."""
    pid = os.getpid()
    return db.acquire_lock(file_path, team_id, agent_id, pid)


def release_lock(db: Database, file_path: str) -> None:
    """Release a file lock."""
    db.release_lock(file_path)


def release_agent_locks(db: Database, agent_id: str) -> int:
    """Release all locks held by a dead/stopped agent."""
    return db.release_agent_locks(agent_id)


def cleanup_dead_locks(db: Database) -> int:
    """Check all locks and release those held by dead PIDs."""
    stale = db.get_stale_locks()
    cleaned = 0
    for lock in stale:
        pid = lock["pid"]
        try:
            os.kill(pid, 0)
        except OSError:
            db.release_lock(lock["file_path"])
            cleaned += 1
    return cleaned
