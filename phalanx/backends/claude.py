"""Claude Code CLI adapter (binary: claude)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentBackend


class ClaudeBackend(AgentBackend):
    name = "claude"

    def binary_name(self) -> str:
        return "claude"

    def detect(self) -> bool:
        return shutil.which("claude") is not None

    def supports_worktree(self) -> bool:
        return True

    def build_interactive_command(
        self,
        prompt: str,
        workspace: Path,
        model: str | None = None,
        worktree: str | None = None,
        soul_file: Path | None = None,
    ) -> list[str]:
        cmd = ["claude"]
        if model:
            cmd += ["--model", model]
        if worktree:
            cmd += ["--worktree", worktree]
        if soul_file:
            cmd += ["--append-system-prompt", soul_file.read_text()]
        if prompt:
            cmd.append(prompt)
        return cmd

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
        cmd = ["claude", "--print"]
        if auto_approve:
            cmd += ["--dangerously-skip-permissions"]
        if model:
            cmd += ["--model", model]
        if worktree:
            cmd += ["--worktree", worktree]
        if json_output:
            cmd += ["--output-format", "stream-json"]
        if soul_file:
            cmd += ["--append-system-prompt", soul_file.read_text()]
        cmd.append(prompt)
        return cmd

    def build_resume_command(
        self,
        chat_id: str,
        message: str | None = None,
    ) -> list[str]:
        cmd = ["claude", "--resume", chat_id, "--print", "--dangerously-skip-permissions"]
        if message:
            cmd.append(message)
        return cmd
