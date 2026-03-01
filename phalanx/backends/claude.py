"""Claude Code CLI backend adapter.

Phase 3: TUI mode only — no --print flag. The agent runs interactively
inside tmux. Output captured via pipe-pane.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .base import AgentBackend


class ClaudeBackend(AgentBackend):
    def name(self) -> str:
        return "claude"

    def binary_name(self) -> str:
        return shutil.which("claude") or "claude"

    def build_start_command(
        self,
        prompt: str,
        soul_file: Path | None = None,
        model: str | None = None,
        worktree: str | None = None,
    ) -> list[str]:
        cmd = [self.binary_name()]
        if model:
            cmd += ["--model", model]
        if soul_file:
            cmd += ["--prompt", f"@{soul_file} {prompt}"]
        else:
            cmd += ["--prompt", prompt]
        return cmd

    def build_resume_command(self, chat_id: str) -> list[str]:
        return [self.binary_name(), "--continue", chat_id]

    def parse_chat_id(self, output: str) -> str | None:
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                for key in ("sessionId", "session_id", "chatId", "chat_id", "id"):
                    if key in obj:
                        return str(obj[key])
            except (json.JSONDecodeError, TypeError):
                pass
        match = re.search(
            r"session[_-]?id[\"']?\s*[:=]\s*[\"']([a-zA-Z0-9_-]+)[\"']",
            output,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    def parse_token_usage(self, output: str) -> dict | None:
        for line in output.splitlines():
            try:
                obj = json.loads(line)
                if "usage" in obj:
                    return obj["usage"]
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def available_models(self) -> list[str]:
        return [
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
        ]

    def auto_approve_flags(self) -> list[str]:
        return ["--dangerously-skip-permissions"]
