"""FakeBackend: a real AgentBackend that runs bash scripts in tmux.

Each behavior produces a shell script that:
1. Echoes FAKE_CHAT_ID=fake-<timestamp> for chat_id persistence testing
2. Sleeps `delay` seconds to simulate work
3. Calls `phalanx agent done` for terminal behaviors (complete, fail, escalate)
4. Then sleeps 3600 so the process stays alive for the grace timer to fire
   (EXCEPT complete_and_exit which exits 0 after artifact, and crash which exits 1)
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from phalanx.backends.base import AgentBackend


# Valid behavior modes
_BEHAVIORS = frozenset({
    "complete",
    "fail",
    "escalate",
    "stall",
    "crash",
    "block",
    "complete_and_exit",
})


class FakeBackend(AgentBackend):
    """Fake backend for E2E testing that runs bash scripts in tmux."""

    def __init__(
        self,
        backend_name: str = "fake",
        behavior: str = "complete",
        delay: float = 2,
    ) -> None:
        if behavior not in _BEHAVIORS:
            raise ValueError(f"Unknown behavior {behavior!r}. Valid: {sorted(_BEHAVIORS)}")
        self._name = backend_name
        self._behavior = behavior
        self._delay = delay

    def build_start_command(
        self,
        prompt: str,
        soul_file: Path | None = None,
        model: str | None = None,
        worktree: str | None = None,
        auto_approve: bool = False,
    ) -> list[str]:
        return ["bash", "-c", self._build_script()]

    def build_resume_command(self, chat_id: str) -> list[str]:
        return ["bash", "-c", self._build_script()]

    def parse_chat_id(self, output: str) -> str | None:
        m = re.search(r"FAKE_CHAT_ID=(fake-[0-9]+)", output)
        return m.group(1) if m else None

    def parse_token_usage(self, output: str) -> dict | None:
        return None

    def list_models(self) -> list[str]:
        return ["fake-model"]

    def name(self) -> str:
        return self._name

    def binary_name(self) -> str:
        return "bash"

    def _build_script(self) -> str:
        ts = int(time.time() * 1000)
        chat_id_line = f'echo "FAKE_CHAT_ID=fake-{ts}"'
        delay_line = f"sleep {self._delay}"

        # Use semicolons instead of newlines to produce single-line scripts.
        # This avoids tmux send_keys(literal=True) triggering shell continuation
        # prompts (dquote>, quote>) which the stall detector misidentifies as
        # buffer corruption.
        if self._behavior == "complete":
            return (
                f'{chat_id_line}; '
                f'{delay_line}; '
                f'phalanx agent done --output \'{{"summary":"fake complete"}}\'; '
                f'exec sleep 3600'
            )
        elif self._behavior == "complete_and_exit":
            return (
                f'{chat_id_line}; '
                f'{delay_line}; '
                f'phalanx agent done --output \'{{"summary":"fake complete and exit"}}\'; '
                f'exit 0'
            )
        elif self._behavior == "fail":
            return (
                f'{chat_id_line}; '
                f'{delay_line}; '
                f'phalanx agent done --output \'{{"error":"fake failure"}}\' --failed; '
                f'exec sleep 3600'
            )
        elif self._behavior == "escalate":
            return (
                f'{chat_id_line}; '
                f'{delay_line}; '
                f'phalanx agent done --output \'{{"reason":"fake escalation"}}\' --escalate; '
                f'exec sleep 3600'
            )
        elif self._behavior == "stall":
            return (
                f'{chat_id_line}; '
                f'{delay_line}; '
                f'exec sleep 3600'
            )
        elif self._behavior == "crash":
            return (
                f'{chat_id_line}; '
                f'{delay_line}; '
                f'exit 1'
            )
        elif self._behavior == "block":
            return (
                f'{chat_id_line}; '
                f'{delay_line}; '
                f'echo "Do you want to proceed? (y/n)"; '
                f'read answer; '
                f'exec sleep 3600'
            )
        else:
            raise ValueError(f"Unknown behavior: {self._behavior}")
