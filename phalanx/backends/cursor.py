"""Cursor CLI backend adapter.

Uses --print mode for automation: agent runs non-interactively, processes the
task, calls phalanx agent done, and exits. The phalanx process manager detects
the exit and reads the artifact from the DB.
"""

from __future__ import annotations

import re
import shutil
import subprocess
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
        auto_approve: bool = False,
    ) -> list[str]:
        cmd = [self.binary_name()]
        if auto_approve:
            cmd.extend(self.auto_approve_flags())
        # --print: non-interactive mode — runs the task, writes output to stdout, then exits.
        # This is the only reliable way to automate cursor agent via tmux because
        # the TUI input box does not respond to Enter via send_keys.
        cmd.append("--print")
        if model:
            cmd += ["--model", model]
        if worktree:
            cmd += ["--worktree", worktree]
        # Pass prompt as positional arg
        prompt_path = Path(prompt)
        if prompt_path.exists():
            cmd.append(f"Read and execute instructions from {prompt_path.absolute()}")
        else:
            cmd.append(prompt)
        return cmd

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
        # Prompt is passed on the command line; no TUI typing needed.
        return False

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
