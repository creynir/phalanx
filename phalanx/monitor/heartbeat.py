"""Heartbeat detection from stream.log file changes."""

from __future__ import annotations

import os
import time
from pathlib import Path


def check_stream_log(stream_log: Path) -> dict:
    """Check if stream.log has been modified recently.

    Returns dict with: exists, mtime, size, age_seconds.
    """
    if not stream_log.exists():
        return {"exists": False, "mtime": 0, "size": 0, "age_seconds": float("inf")}

    stat = stream_log.stat()
    age = time.time() - stat.st_mtime
    return {
        "exists": True,
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "age_seconds": age,
    }


def is_agent_alive(stream_log: Path, stall_seconds: int = 180) -> bool:
    """Return True if stream.log was modified within stall_seconds."""
    info = check_stream_log(stream_log)
    if not info["exists"]:
        return False
    return info["age_seconds"] < stall_seconds


def detect_stall(stream_log: Path, stall_seconds: int = 180) -> bool:
    """Return True if agent appears stalled (log exists but hasn't changed)."""
    info = check_stream_log(stream_log)
    if not info["exists"]:
        return False
    return info["age_seconds"] >= stall_seconds and info["size"] > 0
