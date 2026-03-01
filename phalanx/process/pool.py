"""Process pool for managing multiple agents concurrently."""

from __future__ import annotations

import logging

from phalanx.process.manager import AgentProcess, ProcessManager

logger = logging.getLogger(__name__)


class ProcessPool:
    """Thin wrapper around ProcessManager for bulk operations."""

    def __init__(self, process_manager: ProcessManager) -> None:
        self._pm = process_manager

    def active_count(self) -> int:
        return sum(1 for p in self._pm.list_processes().values() if p.is_alive())

    def kill_all(self) -> list[str]:
        """Kill all managed agent processes."""
        killed = []
        for agent_id in list(self._pm.list_processes()):
            self._pm.kill_agent(agent_id)
            killed.append(agent_id)
        return killed

    def get_alive(self) -> dict[str, AgentProcess]:
        return {aid: proc for aid, proc in self._pm.list_processes().items() if proc.is_alive()}
