"""Cursor CLI adapter (binary: agent)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentBackend


class CursorBackend(AgentBackend):
    name = "cursor"

    def binary_name(self) -> str:
        return "agent"

    def detect(self) -> bool:
        return shutil.which("agent") is not None

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
        cmd = ["agent"]
        if model:
            cmd += ["--model", model]
        if worktree:
            cmd += ["--worktree", worktree]
        cmd += ["--workspace", str(workspace)]
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
        cmd = ["agent", "--print"]
        if model:
            cmd += ["--model", model]
        if worktree:
            cmd += ["--worktree", worktree]
        if json_output:
            cmd += ["--output-format", "stream-json"]
        cmd += ["--workspace", str(workspace)]
        if auto_approve:
            cmd += ["--trust", "--force", "--approve-mcps"]
        cmd.append(prompt)
        return cmd

    def build_resume_command(
        self,
        chat_id: str,
        message: str | None = None,
    ) -> list[str]:
        cmd = ["agent", "--resume", chat_id, "--print", "--force", "--trust"]
        if message:
            cmd.append(message)
        return cmd
