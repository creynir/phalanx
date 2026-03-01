"""ProcessPool — tracks N running agent tmux sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import manager


@dataclass
class AgentProcess:
    agent_id: str
    team_id: str
    session_name: str
    pane_pid: int | None
    stream_log: Path


@dataclass
class ProcessPool:
    """Manages a collection of agent processes for a team."""

    team_id: str
    processes: dict[str, AgentProcess] = field(default_factory=dict)

    def spawn(
        self,
        agent_id: str,
        cmd: list[str],
        stream_log: Path,
        working_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> AgentProcess:
        result = manager.spawn_in_tmux(
            cmd=cmd,
            team_id=self.team_id,
            agent_id=agent_id,
            stream_log=stream_log,
            working_dir=working_dir,
            env=env,
        )
        proc = AgentProcess(
            agent_id=agent_id,
            team_id=self.team_id,
            session_name=result["session_name"],
            pane_pid=result["pane_pid"],
            stream_log=stream_log,
        )
        self.processes[agent_id] = proc
        return proc

    def kill(self, agent_id: str) -> bool:
        proc = self.processes.get(agent_id)
        if proc is None:
            return False
        killed = manager.kill_session(proc.session_name)
        if killed:
            del self.processes[agent_id]
        return killed

    def kill_all(self) -> int:
        count = 0
        for agent_id in list(self.processes.keys()):
            if self.kill(agent_id):
                count += 1
        return count

    def is_alive(self, agent_id: str) -> bool:
        proc = self.processes.get(agent_id)
        if proc is None:
            return False
        return manager.session_exists(proc.session_name)

    def alive_count(self) -> int:
        return sum(1 for aid in self.processes if self.is_alive(aid))
