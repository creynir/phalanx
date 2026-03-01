"""Codex CLI adapter (binary: codex)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentBackend


class CodexBackend(AgentBackend):
    name = "codex"

    def binary_name(self) -> str:
        return "codex"

    def detect(self) -> bool:
        return shutil.which("codex") is not None

    def supports_worktree(self) -> bool:
        return False

    def build_interactive_command(
        self,
        prompt: str,
        workspace: Path,
        model: str | None = None,
        worktree: str | None = None,
        soul_file: Path | None = None,
    ) -> list[str]:
        cmd = ["codex"]
        if model:
            cmd += ["--model", model]
        cmd += ["--cd", str(workspace)]
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
        cmd = ["codex", "exec"]
        if model:
            cmd += ["--model", model]
        cmd += ["--cd", str(workspace)]
        if auto_approve:
            cmd += ["--sandbox", "workspace-write", "-a", "never"]
        cmd.append(prompt)
        return cmd

    def build_resume_command(
        self,
        chat_id: str,
        message: str | None = None,
    ) -> list[str]:
        cmd = ["codex", "resume", "--last"]
        return cmd
