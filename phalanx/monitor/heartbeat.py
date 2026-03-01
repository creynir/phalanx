"""Heartbeat monitor: watches stream.log mtime for agent activity.

Because tmux pipe-pane routes all TUI output to stream.log, this file's
mtime updates whenever the agent produces any screen output — including
during long-running tool calls like `npm install` that print progress.

The heartbeat monitor periodically checks mtime and updates the SQLite
heartbeat timestamp. If the log hasn't grown for the idle threshold
(30 minutes), the agent is considered stalled.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes


@dataclass
class HeartbeatState:
    """Tracks the last known state of a stream.log file."""

    agent_id: str
    stream_log: Path
    last_mtime: float = 0.0
    last_size: int = 0
    last_tail_hash: str = ""
    last_heartbeat: float = 0.0
    idle_timeout: int = IDLE_TIMEOUT_SECONDS

    def is_stale(self, now: float | None = None) -> bool:
        """Has the log not been updated for longer than idle_timeout?"""
        if self.last_heartbeat <= 0:
            return False
        now = now or time.time()
        return (now - self.last_heartbeat) > self.idle_timeout


class HeartbeatMonitor:
    """Monitors stream.log files for agent activity.

    Usage:
        monitor = HeartbeatMonitor()
        monitor.register("agent-1", Path(".phalanx/teams/t1/agents/a1/stream.log"))

        # Periodic check (called from monitor loop)
        result = monitor.check("agent-1")
        if result.is_stale():
            handle_stall(...)
    """

    def __init__(self, idle_timeout: int = IDLE_TIMEOUT_SECONDS) -> None:
        self._states: dict[str, HeartbeatState] = {}
        self._idle_timeout = idle_timeout

    def register(self, agent_id: str, stream_log: Path) -> None:
        """Start tracking an agent's stream.log."""
        self._states[agent_id] = HeartbeatState(
            agent_id=agent_id,
            stream_log=stream_log,
            last_heartbeat=time.time(),
            idle_timeout=self._idle_timeout,
        )
        logger.debug("Registered heartbeat for agent %s at %s", agent_id, stream_log)

    def unregister(self, agent_id: str) -> None:
        """Stop tracking an agent."""
        self._states.pop(agent_id, None)

    def check(self, agent_id: str) -> HeartbeatState | None:
        """Check stream.log for activity and update heartbeat.

        Returns the updated HeartbeatState, or None if agent not registered.
        Activity is detected via mtime + size + tail hash (triple check).
        """
        state = self._states.get(agent_id)
        if state is None:
            return None

        try:
            stat = state.stream_log.stat()
        except FileNotFoundError:
            logger.debug("stream.log not found for %s", agent_id)
            return state

        current_mtime = stat.st_mtime
        current_size = stat.st_size

        # Quick check: mtime or size changed
        if current_mtime != state.last_mtime or current_size != state.last_size:
            state.last_mtime = current_mtime
            state.last_size = current_size
            state.last_tail_hash = self._compute_tail_hash(state.stream_log)
            state.last_heartbeat = time.time()
            logger.debug(
                "Heartbeat updated for %s (mtime=%.1f, size=%d)",
                agent_id,
                current_mtime,
                current_size,
            )
            return state

        # Fallback: check tail hash in case mtime is unreliable (NFS, etc.)
        current_hash = self._compute_tail_hash(state.stream_log)
        if current_hash != state.last_tail_hash:
            state.last_tail_hash = current_hash
            state.last_heartbeat = time.time()
            logger.debug("Heartbeat updated for %s (tail hash changed)", agent_id)

        return state

    def check_all(self) -> dict[str, HeartbeatState]:
        """Check all registered agents and return their states."""
        results = {}
        for agent_id in list(self._states):
            result = self.check(agent_id)
            if result:
                results[agent_id] = result
        return results

    def get_stale_agents(self) -> list[str]:
        """Return IDs of agents whose heartbeat has gone stale."""
        now = time.time()
        stale = []
        for agent_id, state in self._states.items():
            if state.is_stale(now):
                stale.append(agent_id)
        return stale

    def get_state(self, agent_id: str) -> HeartbeatState | None:
        return self._states.get(agent_id)

    @staticmethod
    def _compute_tail_hash(path: Path, tail_bytes: int = 4096) -> str:
        """Hash the last N bytes of the file for change detection."""
        try:
            size = path.stat().st_size
            offset = max(0, size - tail_bytes)
            with open(path, "rb") as f:
                f.seek(offset)
                data = f.read(tail_bytes)
            return hashlib.md5(data).hexdigest()
        except (FileNotFoundError, OSError):
            return ""
