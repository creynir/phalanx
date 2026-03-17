"""Cursor CLI backend adapter.

Phase 3: TUI mode only — no --print flag. The agent runs interactively
inside tmux and all output is captured via pipe-pane.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .base import AgentBackend


_CLAUDE_TO_CURSOR_MODEL: dict[str, str] = {
    # Claude API model names → cursor agent model names
    "claude-opus-4-6": "opus-4.6",
    "claude-sonnet-4-6": "sonnet-4.6",
    "claude-haiku-4-5": "haiku-4.5",
    "claude-opus-4-5": "opus-4.5",
    "claude-sonnet-4-5": "sonnet-4.5",
}


class CursorBackend(AgentBackend):
    def name(self) -> str:
        return "cursor"

    def binary_name(self) -> str:
        return shutil.which("agent") or "agent"

    def _normalize_model(self, model: str) -> str:
        """Map claude API model names to cursor agent model names."""
        return _CLAUDE_TO_CURSOR_MODEL.get(model, model)

    def build_start_command(
        self,
        prompt: str,
        soul_file: Path | None = None,
        model: str | None = None,
        worktree: str | None = None,
        auto_approve: bool = False,
    ) -> list[str]:
        cmd = [self.binary_name()]
        if auto_approve:
            cmd.extend(self.auto_approve_flags())
        if model:
            cmd += ["--model", self._normalize_model(model)]
        if worktree:
            cmd += ["--worktree", worktree]
        return cmd

    def format_deferred_prompt(self, prompt: str) -> str:
        prompt_path = Path(prompt)
        if prompt_path.exists():
            return f"Read and execute instructions from {prompt_path.absolute()}"
        return prompt

    def build_resume_command(self, chat_id: str) -> list[str]:
        return [self.binary_name(), "--resume", chat_id]

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

    def list_models(self) -> list[str]:
        try:
            result = subprocess.run(
                [self.binary_name(), "--model", "--help"],
                capture_output=True,
                text=True,
            )
            marker = "Available models: "
            if marker in result.stderr:
                models_str = result.stderr.split(marker, 1)[1]
                # Trim at the first newline or end of string
                models_str = models_str.split("\n")[0].strip()
                return [m.strip() for m in models_str.split(", ") if m.strip()]
        except Exception:
            pass
        return []

    def auto_approve_flags(self) -> list[str]:
        return ["--yolo"]

    def deferred_prompt(self) -> bool:
        return True

    def tui_ready_indicator(self) -> str:
        return "/ commands"

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
