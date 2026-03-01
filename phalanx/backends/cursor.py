"""Cursor CLI backend adapter.

Phase 3: TUI mode only — no --print flag. The agent runs interactively
inside tmux and all output is captured via pipe-pane.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .base import AgentBackend


class CursorBackend(AgentBackend):
    def name(self) -> str:
        return "cursor"

    def binary_name(self) -> str:
        return shutil.which("cursor") or "cursor"

    def build_start_command(
        self,
        prompt: str,
        soul_file: Path | None = None,
        model: str | None = None,
        worktree: str | None = None,
    ) -> list[str]:
        cmd = [self.binary_name()]
        cmd += ["--force", "--trust"]
        if model:
            cmd += ["--model", model]
        if worktree:
            cmd += ["--worktree", worktree]
        if soul_file:
            cmd += ["--prompt", f"@{soul_file} {prompt}"]
        else:
            cmd += ["--prompt", prompt]
        return cmd

    def build_resume_command(self, chat_id: str) -> list[str]:
        return [self.binary_name(), "--resume", chat_id, "--force", "--trust"]

    def parse_chat_id(self, output: str) -> str | None:
        match = re.search(
            r"chat[_-]?id[\"']?\s*[:=]\s*[\"']([a-zA-Z0-9_-]+)[\"']",
            output,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    def parse_token_usage(self, output: str) -> dict | None:
        match = re.search(r"tokens?\s*[:=]\s*(\d+)", output, re.IGNORECASE)
        if match:
            return {"tokens": int(match.group(1))}
        return None

    def available_models(self) -> list[str]:
        return [
            "claude-sonnet-4-20250514",
            "gpt-4.1",
            "gemini-2.5-pro",
            "o3",
        ]

    def auto_approve_flags(self) -> list[str]:
        return ["--force", "--trust"]
