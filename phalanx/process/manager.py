"""libtmux-based process management for agent sessions."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import libtmux
from libtmux._internal.query_list import ObjectDoesNotExist


SESSION_PREFIX = "phalanx"


def _session_name(team_id: str, agent_id: str) -> str:
    return f"{SESSION_PREFIX}-{team_id}-{agent_id}"


def get_server() -> libtmux.Server:
    return libtmux.Server()


def spawn_in_tmux(
    cmd: list[str],
    team_id: str,
    agent_id: str,
    stream_log: Path,
    working_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a tmux session and run cmd, piping output to stream_log.

    Returns dict with session_name, pane_pid.
    """
    server = get_server()
    sess_name = _session_name(team_id, agent_id)

    stream_log.parent.mkdir(parents=True, exist_ok=True)

    session = server.new_session(
        session_name=sess_name,
        start_directory=str(working_dir) if working_dir else None,
    )
    pane = session.active_window.active_pane

    if env:
        for k, v in env.items():
            pane.send_keys(f"export {k}={shlex.quote(v)}", enter=True)

    full_cmd = f"{shlex.join(cmd)} 2>&1 | tee {shlex.quote(str(stream_log))}"
    pane.send_keys(full_cmd, enter=True)

    pane_pid = get_pane_pid(pane)

    return {
        "session_name": sess_name,
        "pane_pid": pane_pid,
    }


def send_keys_to_session(session_name: str, text: str) -> bool:
    """Send keys to the active pane of a tmux session. Returns True on success."""
    server = get_server()
    try:
        session = server.sessions.get(session_name=session_name)
    except ObjectDoesNotExist:
        return False
    pane = session.active_window.active_pane
    pane.send_keys(text, enter=True)
    return True


def kill_session(session_name: str) -> bool:
    """Kill a tmux session. Returns True if it existed."""
    server = get_server()
    try:
        session = server.sessions.get(session_name=session_name)
    except ObjectDoesNotExist:
        return False
    session.kill()
    return True


def session_exists(session_name: str) -> bool:
    server = get_server()
    try:
        server.sessions.get(session_name=session_name)
        return True
    except ObjectDoesNotExist:
        return False


def list_phalanx_sessions() -> list[str]:
    """List all tmux sessions with the phalanx prefix."""
    server = get_server()
    return [
        s.name
        for s in server.sessions
        if s.name and s.name.startswith(SESSION_PREFIX)
    ]


def get_pane_pid(pane: Any) -> int | None:
    """Extract the PID of the process running in a tmux pane."""
    try:
        pid_str = pane.pane_pid
        return int(pid_str) if pid_str else None
    except (AttributeError, ValueError):
        return None


def capture_pane_output(session_name: str, lines: int = 50) -> str | None:
    """Capture recent output from a tmux pane."""
    server = get_server()
    try:
        session = server.sessions.get(session_name=session_name)
    except ObjectDoesNotExist:
        return None
    pane = session.active_window.active_pane
    output = pane.capture_pane()
    if isinstance(output, list):
        return "\n".join(output[-lines:])
    return str(output)
