"""Message delivery to agents via file-based injection.

v1.0.0: ALL message delivery uses file-based injection to eliminate
prompt injection vulnerabilities from tmux send-keys. Only single
characters (e.g. 'y', 'a' for prompt resolution) use raw send-keys.

The message content is written to a temp file and only the file path
is injected into the TUI via send-keys.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)

LONG_MESSAGE_THRESHOLD = 500

_POISON_PILL_PATTERNS = re.compile(
    r"escalation_required|"
    r"\\x[0-9a-fA-F]{2}|"
    r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
)


def sanitize_for_send_keys(text: str) -> str:
    """Sanitize text before injection via send_keys.

    Strips known TUI-crashing patterns and non-printable control characters.
    Only used for short delivery hints — actual content goes via files.
    """
    return _POISON_PILL_PATTERNS.sub("", text)


def deliver_message(
    process_manager: ProcessManager,
    agent_id: str,
    message: str,
    message_dir: Path | None = None,
) -> bool:
    """Deliver a message to an agent's tmux pane via file-based injection.

    Always delivers via file to avoid shell injection from message content.
    """
    return _deliver_via_file(process_manager, agent_id, message, message_dir)


def broadcast_message(
    process_manager: ProcessManager,
    db,
    team_id: str,
    message: str,
    exclude_agent_id: str | None = None,
    message_dir: Path | None = None,
) -> dict[str, bool]:
    """Deliver a message to all agents in a team.

    Returns {agent_id: success} for each delivery attempt.
    """
    agents = db.list_agents(team_id)
    results = {}

    for agent in agents:
        agent_id = agent["id"]
        if agent_id == exclude_agent_id:
            continue
        if agent["status"] != "running":
            results[agent_id] = False
            continue

        results[agent_id] = deliver_message(process_manager, agent_id, message, message_dir)

    return results


def _deliver_via_file(
    process_manager: ProcessManager,
    agent_id: str,
    message: str,
    message_dir: Path | None = None,
) -> bool:
    """Write message to a file and tell the agent to read it.

    The only text sent via send_keys is the sanitized file path reference.
    """
    if message_dir is None:
        import tempfile

        message_dir = Path(tempfile.gettempdir()) / "phalanx_messages"
    message_dir.mkdir(parents=True, exist_ok=True)

    msg_file = message_dir / f"msg_{agent_id}_{hash(message) & 0xFFFFFFFF:08x}.txt"
    msg_file.write_text(message, encoding="utf-8")

    delivery_text = sanitize_for_send_keys(f"Read and respond to the message at: {msg_file}")
    return process_manager.send_keys(agent_id, delivery_text, enter=True)
