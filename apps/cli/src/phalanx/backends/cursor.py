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
        return shutil.which("agent") or "agent"

    def build_start_command(
        self,
        prompt: str,
        soul_file: Path | None = None,
        model: str | None = None,
        worktree: str | None = None,
        auto_approve: bool = True,
    ) -> list[str]:
        cmd = [self.binary_name()]
        if model:
            cmd += ["--model", model]
        if worktree:
            cmd += ["--worktree", worktree]
        # For Cursor TUI, passing a massive inline string with newlines
        # via tmux send-keys causes shell buffer corruption.
        # Instead, we pass a short instruction to read the file.
        prompt_path = Path(prompt)
        if prompt_path.exists():
            cmd.append(f"Read and execute instructions from {prompt_path.absolute()}")
        else:
            cmd.append(prompt)
        return cmd

    def build_resume_command(self, chat_id: str, auto_approve: bool = False) -> list[str]:
        cmd = [self.binary_name()]
        if auto_approve:
            cmd.extend(self.auto_approve_flags())
        cmd.extend(["--resume", chat_id])
        return cmd

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
        return ["--yolo"]

    def spawn_delay(self) -> float:
        # Cursor agent processes share ~/.cursor/cli-config.json and race to
        # rewrite it on startup. A 3-second stagger between spawns is enough
        # for each process to finish its config init before the next starts.
        # Set PHALANX_CURSOR_SPAWN_DELAY=0 to disable (e.g. in tests).
        import os

        env_val = os.environ.get("PHALANX_CURSOR_SPAWN_DELAY")
        if env_val is not None:
            return float(env_val)
        return 3.0
