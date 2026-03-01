"""Abstract base class for agent CLI backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class AgentBackend(ABC):
    """Interface every CLI adapter must implement."""

    name: str

    @abstractmethod
    def build_interactive_command(
        self,
        prompt: str,
        workspace: Path,
        model: str | None = None,
        worktree: str | None = None,
        soul_file: Path | None = None,
    ) -> list[str]:
        """Command for TUI mode (user-facing agent)."""

    @abstractmethod
    def build_headless_command(
        self,
        prompt: str,
        workspace: Path,
        model: str | None = None,
        worktree: str | None = None,
        soul_file: Path | None = None,
        json_output: bool = True,
        auto_approve: bool = True,
    ) -> list[str]:
        """Command for --print / headless mode (team agents in tmux)."""

    @abstractmethod
    def build_resume_command(
        self,
        chat_id: str,
        message: str | None = None,
    ) -> list[str]:
        """Resume an existing session."""

    @abstractmethod
    def detect(self) -> bool:
        """Return True if this CLI is installed and available."""

    @abstractmethod
    def supports_worktree(self) -> bool:
        """Whether the CLI has native --worktree support."""

    @abstractmethod
    def binary_name(self) -> str:
        """The CLI binary name (e.g. 'agent', 'claude')."""
