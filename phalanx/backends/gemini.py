"""Gemini CLI adapter (binary: gemini)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentBackend


class GeminiBackend(AgentBackend):
    name = "gemini"

    def binary_name(self) -> str:
        return "gemini"

    def detect(self) -> bool:
        return shutil.which("gemini") is not None

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
        cmd = ["gemini"]
        if model:
            cmd += ["--model", model]
        if soul_file:
            cmd += ["--policy", str(soul_file)]
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
        cmd = ["gemini"]
        if model:
            cmd += ["--model", model]
        if json_output:
            cmd += ["-o", "stream-json"]
        if soul_file:
            cmd += ["--policy", str(soul_file)]
        if auto_approve:
            cmd += ["--yolo"]
        cmd += ["-p", prompt]
        return cmd

    def build_resume_command(
        self,
        chat_id: str,
        message: str | None = None,
    ) -> list[str]:
        cmd = ["gemini", "--resume", chat_id, "--yolo"]
        if message:
            cmd += ["-p", message]
        return cmd
