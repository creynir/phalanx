"""Message delivery to agents via tmux send-keys.

Push-only delivery: messages are sent immediately via send-keys.
The terminal input buffer queues them until the agent's next input read.
No Ctrl+C interrupt — the agent picks up the message naturally.

Long messages (>500 chars) are written to a temp file and the agent
is told to read that file instead.
"""

from __future__ import annotations

import logging
from pathlib import Path

from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)

LONG_MESSAGE_THRESHOLD = 500


def deliver_message(
    process_manager: ProcessManager,
    agent_id: str,
    message: str,
    message_dir: Path | None = None,
) -> bool:
    """Deliver a message to an agent's tmux pane via send-keys.

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
    """Write message to a file and tell the agent to read it."""
    if message_dir is None:
        import tempfile

        message_dir = Path(tempfile.gettempdir()) / "phalanx_messages"
    message_dir.mkdir(parents=True, exist_ok=True)

    msg_file = message_dir / f"msg_{agent_id}_{hash(message) & 0xFFFFFFFF:08x}.txt"
    msg_file.write_text(message, encoding="utf-8")

    delivery_text = f"Read and respond to the message at: {msg_file}"
    return process_manager.send_keys(agent_id, delivery_text, enter=True)
