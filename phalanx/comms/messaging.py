"""Message delivery to agents via tmux send_keys."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from phalanx.process.manager import send_keys_to_session

LONG_MESSAGE_THRESHOLD = 500

# tmux send_keys interprets C-* and M-* as control/meta sequences.
# Strip or escape anything that could be interpreted as a tmux special key.
_TMUX_ESCAPE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_for_sendkeys(text: str) -> str:
    """Remove control characters that tmux could interpret as commands."""
    return _TMUX_ESCAPE_RE.sub("", text)


def deliver_message(
    session_name: str,
    message: str,
    team_dir: Path | None = None,
) -> bool:
    """Send a message to an agent's tmux pane.

    Short messages are sent directly (sanitized). Long messages (>500 chars)
    are written to a file to avoid character dropping in send_keys.
    """
    if len(message) <= LONG_MESSAGE_THRESHOLD:
        return send_keys_to_session(session_name, _sanitize_for_sendkeys(message))

    # Long messages always go through file to avoid injection and dropping
    if team_dir is None:
        team_dir = Path(tempfile.gettempdir())

    msg_dir = team_dir / "messages"
    msg_dir.mkdir(parents=True, exist_ok=True)

    msg_file = tempfile.NamedTemporaryFile(
        dir=str(msg_dir), suffix=".md", delete=False, mode="w",
    )
    msg_file.write(message)
    msg_file.close()

    instruction = f"Read the message at {msg_file.name} and follow the instructions within."
    return send_keys_to_session(session_name, _sanitize_for_sendkeys(instruction))
