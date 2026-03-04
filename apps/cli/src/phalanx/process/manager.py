"""Process manager: spawn agents in TUI mode inside tmux.

Phase 3 design:
- Agents run interactively in tmux (no --print flag).
- `tmux pipe-pane` streams all TUI output to stream.log, which the
  HeartbeatMonitor watches for activity.
- To interrupt a busy agent, send Ctrl+C twice via send-keys.
  Wait up to 10s for the prompt to return. If it doesn't, SIGKILL
  the agent and restart with --resume.
- To send a message to an idle agent, use send-keys directly.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import libtmux

from phalanx.backends.base import AgentBackend

logger = logging.getLogger(__name__)

INTERRUPT_WAIT_SECONDS = 10
INTERRUPT_POLL_INTERVAL = 0.5


def _find_source_root() -> Path | None:
    """Return the phalanx source project root if we're running from a dev checkout.

    Walks up from this file to find a pyproject.toml, then verifies it's the
    phalanx project. Returns None when running from an installed wheel.
    """
    candidate = Path(__file__).resolve().parent
    for _ in range(4):
        candidate = candidate.parent
        pyproject = candidate / "pyproject.toml"
        if pyproject.exists() and 'name = "phalanx' in pyproject.read_text():
            return candidate
    return None


_SOURCE_ROOT: Path | None = _find_source_root()


def _resolve_uv_bin() -> str:
    """Return the absolute path to the uv binary.

    Tries the venv sibling first (uv is often installed alongside python),
    then falls back to PATH lookup.
    """
    import shutil

    venv_uv = Path(sys.executable).parent / "uv"
    if venv_uv.exists():
        return str(venv_uv)
    found = shutil.which("uv")
    if found:
        return found
    return "uv"  # last resort: let the shell resolve it


@dataclass
class AgentProcess:
    """Represents a running agent inside a tmux session."""

    agent_id: str
    team_id: str
    session_name: str
    stream_log: Path
    backend: AgentBackend
    chat_id: str | None = None
    _session: libtmux.Session | None = field(default=None, repr=False)

    @property
    def pane(self) -> libtmux.Pane | None:
        try:
            server = libtmux.Server()
            session = server.sessions.get(session_name=self.session_name)
            if session:
                return session.active_window.active_pane
            return None
        except Exception:
            return None

    # Shells that indicate the agent binary has exited and tmux fell
    # back to an interactive prompt (a "ghost session").
    _GHOST_SHELLS = frozenset({"zsh", "bash", "sh", "fish", "dash", "csh", "tcsh", "ksh"})

    def is_alive(self) -> bool:
        """Check if the agent process is alive inside its tmux session.

        Returns False if:
        - The tmux session no longer exists.
        - The pane's current command is a bare shell (zsh, bash, etc.),
          which means the agent binary crashed or exited and the session
          fell back to an interactive shell prompt ("ghost session").
        - The pane screen shows shell error spam (corroborated ghost check).
        """
        try:
            server = libtmux.Server()
            session = server.sessions.get(session_name=self.session_name)
        except Exception:
            return False

        try:
            pane = session.active_window.active_pane
            if pane is None:
                return False
        except Exception:
            return False

        try:
            current_cmd = pane.pane_current_command
            if current_cmd and current_cmd.strip().split("/")[-1] in self._GHOST_SHELLS:
                return False
        except Exception:
            pass

        try:
            screen = pane.capture_pane()
            if screen and self._screen_shows_ghost(screen):
                return False
        except Exception:
            pass

        return True

    @staticmethod
    def _screen_shows_ghost(lines: list[str]) -> bool:
        """Corroborate ghost detection via screen content.

        Returns True if the screen shows patterns consistent with the
        agent binary having exited: multiple shell errors, or a bare
        shell prompt with no TUI chrome.
        """
        import re

        if not lines:
            return False
        tail = "\n".join(lines[-12:])

        shell_error_count = len(
            re.findall(
                r"zsh:|bash:|sh:|command not found|parse error|no such file",
                tail,
                re.IGNORECASE,
            )
        )
        if shell_error_count >= 2:
            return True

        last_lines = [ln.strip() for ln in lines[-4:] if ln.strip()]
        if last_lines:
            last = last_lines[-1]
            tui_indicators = ("❯", "? for shortcuts", "→ Add a follow-up", "/ commands · @")
            if any(ind in last for ind in tui_indicators):
                return False
            if re.match(r"^[\w@.~/ ()-]*[$%#>]\s*$", last):
                return True

        return False


class ProcessManager:
    """Manages agent processes in tmux sessions with TUI mode."""

    def __init__(self, phalanx_root: Path) -> None:
        self._root = phalanx_root
        self._server: libtmux.Server | None = None
        self._processes: dict[str, AgentProcess] = {}

    @property
    def server(self) -> libtmux.Server:
        if self._server is None:
            self._server = libtmux.Server()
        return self._server

    def _session_name(self, team_id: str, agent_id: str) -> str:
        return f"phalanx-{team_id}-{agent_id}"

    def _stream_log_path(self, team_id: str, agent_id: str) -> Path:
        agent_dir = self._root / "teams" / team_id / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir / "stream.log"

    def spawn(
        self,
        team_id: str,
        agent_id: str,
        backend: AgentBackend,
        prompt: str,
        soul_file: Path | None = None,
        model: str | None = None,
        worktree: str | None = None,
        working_dir: str | None = None,
        auto_approve: bool = False,
    ) -> AgentProcess:
        """Spawn an agent in TUI mode inside a new tmux session.

        1. Create tmux session
        2. Set up pipe-pane to stream.log
        3. Send the CLI command into the pane via send-keys
        """
        session_name = self._session_name(team_id, agent_id)
        stream_log = self._stream_log_path(team_id, agent_id)

        # Clean up stale session if it exists
        self._kill_session(session_name)

        # Ensure stream.log is fresh
        stream_log.parent.mkdir(parents=True, exist_ok=True)
        stream_log.write_text("")

        # Create tmux session
        kwargs = {}
        if working_dir:
            kwargs["start_directory"] = working_dir

        # Pass environment variables so agents know who they are
        kwargs["environment"] = {
            "PHALANX_TEAM_ID": team_id,
            "PHALANX_AGENT_ID": agent_id,
        }

        session = self.server.new_session(
            session_name=session_name,
            **kwargs,
        )

        # Set up pipe-pane to capture all TUI output into stream.log
        try:
            self._setup_pipe_pane(session_name, stream_log)
        except Exception as e:
            logger.error("Failed to set up pipe-pane for session %s: %s", session_name, e)
            self._kill_session(session_name)
            raise

        pane = session.active_window.active_pane
        self._setup_agent_env(pane, agent_id, team_id)

        # Build the TUI command (no --print)
        cmd_parts = backend.build_start_command(
            prompt=prompt,
            soul_file=soul_file,
            model=model,
            worktree=worktree,
        )

        if auto_approve:
            approve_flags = backend.auto_approve_flags()
            for flag in approve_flags:
                if flag not in cmd_parts:
                    cmd_parts.insert(1, flag)

        cmd_str = shlex.join(cmd_parts)
        pane.send_keys(cmd_str, enter=True, literal=True)

        agent_proc = AgentProcess(
            agent_id=agent_id,
            team_id=team_id,
            session_name=session_name,
            stream_log=stream_log,
            backend=backend,
            _session=session,
        )
        self._processes[agent_id] = agent_proc

        logger.info(
            "Spawned agent %s in tmux session %s (TUI mode)",
            agent_id,
            session_name,
        )
        return agent_proc

    def spawn_resume(
        self,
        team_id: str,
        agent_id: str,
        backend: AgentBackend,
        chat_id: str,
        working_dir: str | None = None,
        auto_approve: bool = False,
    ) -> AgentProcess:
        """Resume an agent session using --resume/--continue."""
        session_name = self._session_name(team_id, agent_id)
        stream_log = self._stream_log_path(team_id, agent_id)

        self._kill_session(session_name)
        stream_log.write_text("")

        env = {}
        if working_dir:
            env["start_directory"] = working_dir

        session = self.server.new_session(
            session_name=session_name,
            **env,
        )

        self._setup_pipe_pane(session_name, stream_log)

        pane = session.active_window.active_pane
        self._setup_agent_env(pane, agent_id, team_id)

        cmd_parts = backend.build_resume_command(chat_id)

        if auto_approve:
            approve_flags = backend.auto_approve_flags()
            for flag in approve_flags:
                if flag not in cmd_parts:
                    cmd_parts.insert(1, flag)

        cmd_str = shlex.join(cmd_parts)
        pane.send_keys(cmd_str, enter=True, literal=True)

        agent_proc = AgentProcess(
            agent_id=agent_id,
            team_id=team_id,
            session_name=session_name,
            stream_log=stream_log,
            backend=backend,
            chat_id=chat_id,
            _session=session,
        )
        self._processes[agent_id] = agent_proc

        logger.info(
            "Resumed agent %s in tmux session %s (chat_id=%s)",
            agent_id,
            session_name,
            chat_id,
        )
        return agent_proc

    def send_keys(
        self,
        agent_id: str,
        keys: str,
        enter: bool = True,
    ) -> bool:
        """Send keystrokes to an agent's tmux pane.

        Used for:
        - Sending messages to an idle agent
        - Responding to prompts (e.g., workspace trust)
        - Any other keystroke injection
        """
        pane = None
        proc = self._processes.get(agent_id)
        if proc:
            pane = proc.pane

        if pane is None:
            # Fallback: try to find it in tmux sessions if not tracked in memory
            # This handles cases where CLI commands are run in a separate process
            for s in self.server.sessions:
                if s.name and s.name.endswith(f"-{agent_id}"):
                    if s.panes:
                        pane = s.panes[0]
                        break

        if pane is None:
            logger.warning("Agent %s has no active pane", agent_id)
            return False

        try:
            pane.send_keys(keys, enter=enter, suppress_history=False)
            logger.debug("Sent keys to agent %s: %r", agent_id, keys[:100])
            return True
        except Exception as e:
            logger.error("Failed to send keys to agent %s: %s", agent_id, e)
            return False

    def interrupt_agent(
        self,
        agent_id: str,
        screen_checker=None,
    ) -> bool:
        """Interrupt a busy agent with Ctrl+C Ctrl+C."""
        pane = None
        proc = self._processes.get(agent_id)
        if proc:
            pane = proc.pane

        if pane is None:
            # Fallback for unconnected processes
            for s in self.server.sessions:
                if s.name and s.name.endswith(f"-{agent_id}"):
                    if s.panes:
                        pane = s.panes[0]
                        break

        if pane is None:
            logger.warning("Agent %s has no active pane for interrupt", agent_id)
            return False

        seq = proc.backend.interrupt_sequence() if proc else ["C-c", "C-c"]
        for key in seq:
            pane.send_keys(key, enter=False)
            time.sleep(0.3)

        logger.info("Sent %s to agent %s, waiting for prompt...", " ".join(seq), agent_id)

        # Wait for the prompt to return
        deadline = time.time() + INTERRUPT_WAIT_SECONDS
        while time.time() < deadline:
            time.sleep(INTERRUPT_POLL_INTERVAL)
            try:
                screen = pane.capture_pane()
                if screen_checker:
                    if screen_checker(screen):
                        logger.info("Agent %s prompt returned after interrupt", agent_id)
                        return True
                else:
                    # Default heuristic: look for common prompt indicators
                    tail = "\n".join(screen[-5:]) if screen else ""
                    if _looks_like_prompt(tail):
                        logger.info("Agent %s prompt returned after interrupt", agent_id)
                        return True
            except Exception as e:
                logger.debug("Error capturing pane for agent %s: %s", agent_id, e)

        logger.warning(
            "Agent %s did not return to prompt within %ds after interrupt",
            agent_id,
            INTERRUPT_WAIT_SECONDS,
        )
        return False

    def kill_agent(self, agent_id: str) -> None:
        """Kill an agent's tmux session."""
        proc = self._processes.pop(agent_id, None)
        if proc:
            self._kill_session(proc.session_name)
            logger.info("Killed agent %s (session %s)", agent_id, proc.session_name)
        else:
            # Fallback for separate CLI process
            killed = False
            for s in self.server.sessions:
                if s.name and s.name.endswith(f"-{agent_id}"):
                    self._kill_session(s.name)
                    logger.info("Killed agent %s (session %s)", agent_id, s.name)
                    killed = True
            if not killed:
                logger.debug("Agent %s not found for kill", agent_id)

    def capture_screen(self, agent_id: str) -> list[str] | None:
        """Capture the current tmux pane contents for an agent.

        Used by the stall detector / TUI screen scraper.
        """
        proc = self._processes.get(agent_id)
        if not proc:
            return None
        pane = proc.pane
        if pane is None:
            return None
        try:
            return pane.capture_pane()
        except Exception as e:
            logger.debug("Error capturing screen for %s: %s", agent_id, e)
            return None

    def get_process(self, agent_id: str) -> AgentProcess | None:
        return self._processes.get(agent_id)

    def discover_agent(
        self, team_id: str, agent_id: str, backend: AgentBackend | None = None
    ) -> AgentProcess | None:
        """Discover an existing agent tmux session and register it.

        Used by the monitor daemon which starts fresh without spawned processes.
        """
        session_name = self._session_name(team_id, agent_id)
        try:
            session = self.server.sessions.get(session_name=session_name)
        except Exception:
            return None

        agent_dir = self._root / "teams" / team_id / "agents" / agent_id
        stream_log = agent_dir / "stream.log"

        proc = AgentProcess(
            agent_id=agent_id,
            team_id=team_id,
            session_name=session_name,
            stream_log=stream_log,
            backend=backend,
            _session=session,
        )
        self._processes[agent_id] = proc
        return proc

    def list_processes(self) -> dict[str, AgentProcess]:
        return dict(self._processes)

    # --- internal ---

    def _setup_agent_env(self, pane: libtmux.Pane, agent_id: str, team_id: str) -> None:
        """Export identity env vars and dev phalanx alias into the agent's shell.

        Called from both spawn() and spawn_resume() so resumed agents have the
        same environment as freshly spawned ones.
        """
        export_cmd = (
            f"export PHALANX_AGENT_ID={shlex.quote(agent_id)} "
            f"PHALANX_TEAM_ID={shlex.quote(team_id)} "
            f"PHALANX_ROOT={shlex.quote(str(self._root))}"
        )
        pane.send_keys(export_cmd, enter=True)

        if _SOURCE_ROOT is not None:
            uv_bin = shlex.quote(_resolve_uv_bin())
            src = shlex.quote(str(_SOURCE_ROOT))
            alias_cmd = (
                f'phalanx() {{ {uv_bin} run --project {src} phalanx "$@"; }}; export -f phalanx'
            )
            pane.send_keys(alias_cmd, enter=True)

    def _setup_pipe_pane(self, session_name: str, stream_log: Path) -> None:
        """Set up tmux pipe-pane to stream TUI output into stream.log."""
        subprocess.run(
            [
                "tmux",
                "pipe-pane",
                "-t",
                session_name,
                "-o",
                f"cat >> {shlex.quote(str(stream_log))}",
            ],
            check=True,
            capture_output=True,
        )
        logger.debug("pipe-pane set up: %s -> %s", session_name, stream_log)

    def _kill_session(self, session_name: str) -> None:
        """Kill a tmux session if it exists."""
        try:
            session = self.server.sessions.get(session_name=session_name)
            session.kill()
        except Exception as e:
            logger.debug("Failed to kill session %s: %s", session_name, e)


def _looks_like_prompt(text: str) -> bool:
    """Heuristic: does the text look like an agent waiting for input?

    Checks for common prompt indicators across different CLI tools.
    """
    indicators = [
        "❯",  # Claude Code prompt
        "? for shortcuts",  # Claude Code help hint
        "→ Add a follow-up",  # Cursor TUI idle prompt
        "/ commands · @",  # Cursor TUI bottom bar (idle state)
        "> ",  # Generic prompt
        ">>>",  # Python-style prompt
        "$ ",  # Shell prompt (agent returned to shell)
    ]
    for indicator in indicators:
        if indicator in text:
            return True
    return False
