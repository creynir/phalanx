"""Abstract base class for agent backend adapters.

Each backend knows how to build CLI commands for a specific agent tool
(Cursor, Claude, Gemini, Codex). Backends are thin — they only know
about binary paths, CLI flags, and output parsing.

Phase 3: All commands produce TUI-mode invocations (no --print).
The agent runs interactively inside tmux and output is captured via
tmux pipe-pane into stream.log.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class AgentBackend(ABC):
    """Thin adapter for different agent CLIs."""

    @abstractmethod
    def build_start_command(
        self,
        prompt: str,
        soul_file: Path | None = None,
        model: str | None = None,
        worktree: str | None = None,
    ) -> list[str]:
        """Build the CLI command to start a new agent session in TUI mode.

        The returned command is meant to be sent into a tmux pane via
        send_keys — it runs interactively (no --print).
        """

    @abstractmethod
    def build_resume_command(self, chat_id: str) -> list[str]:
        """Build the CLI command to resume an existing session."""

    @abstractmethod
    def parse_chat_id(self, output: str) -> str | None:
        """Extract chat/session ID from agent output."""

    @abstractmethod
    def parse_token_usage(self, output: str) -> dict | None:
        """Extract token/cost info from agent output."""

    @abstractmethod
    def available_models(self) -> list[str]:
        """List models available through this backend."""

    @abstractmethod
    def name(self) -> str:
        """Backend identifier (e.g. 'cursor', 'claude')."""

    @abstractmethod
    def binary_name(self) -> str:
        """Name or path of the CLI binary."""

    def auto_approve_flags(self) -> list[str]:
        """Flags to enable auto-approval of tool calls, if any."""
        return []

    def spawn_delay(self) -> float:
        """Seconds to wait after spawning an agent before spawning the next.

        Used to avoid filesystem races in backends that share config files
        between concurrent instances (e.g. Cursor cli-config.json).
        Default is 0 (no delay). Backends that need staggering override this.
        """
        return 0.0

    def interrupt_sequence(self) -> list[str]:
        """List of tmux keys to send to interrupt the agent and return to prompt."""
        return ["C-c", "C-c"]
