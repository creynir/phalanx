"""Claude Code CLI backend adapter.

Phase 3: TUI mode only — no --print flag. The agent runs interactively
inside tmux. Output captured via pipe-pane.

Prompt delivery: Claude uses the deferred prompt approach (like Cursor).
`build_start_command` launches Claude without a file arg so the TUI
initialises fully. Once the `❯` prompt is visible, `format_deferred_prompt`
sends `@/path/to/task.md` as the first message — which Claude processes as
an instruction to execute rather than passive context.
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
        auto_approve: bool = False,
    ) -> list[str]:
        # Do NOT pass @prompt here — Claude treats CLI @file args as context
        # and then asks "what would you like to do?".  The task is delivered
        # after TUI initialisation via format_deferred_prompt() instead.
        cmd = [self.binary_name()]
        if auto_approve:
            cmd.extend(self.auto_approve_flags())
        if model:
            cmd += ["--model", model]
        return cmd

    def deferred_prompt(self) -> bool:
        return True

    def tui_ready_indicator(self) -> str:
        # ❯ appears as the input prompt once the TUI is idle and ready.
        # Works regardless of mode (normal or --dangerously-skip-permissions,
        # which shows "bypass permissions on" instead of "? for shortcuts").
        return "❯"

    def format_deferred_prompt(self, prompt: str) -> str:
        # Send the task file as a @-reference so Claude reads the full content.
        # The task.md always starts with "Execute the following task immediately
        # without summarising or asking questions:" which triggers execution.
        prompt_path = Path(prompt)
        if prompt_path.exists():
            return f"@{prompt_path.absolute()}"
        return prompt

    def build_resume_command(self, chat_id: str) -> list[str]:
        return [self.binary_name(), "--continue", chat_id]

    def interrupt_sequence(self) -> list[str]:
        return ["Escape", "C-c"]

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
