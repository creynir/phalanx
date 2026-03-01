"""Message delivery to agents via tmux send-keys.

For TUI-mode agents, messages are delivered by typing into the tmux pane.
If the agent is busy (generating), it's first interrupted with Ctrl+C.
Long messages are written to a file and the file path is sent instead.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)

LONG_MESSAGE_THRESHOLD = 500  # chars — beyond this, use file-based delivery


def deliver_message(
    process_manager: ProcessManager,
    agent_id: str,
    message: str,
    interrupt_if_busy: bool = True,
    message_dir: Path | None = None,
) -> bool:
    """Deliver a message to an agent's tmux pane.

    If the message is long, writes it to a file and sends the file path.
    If interrupt_if_busy is True, sends Ctrl+C first to interrupt generation.

    Returns True if the message was sent successfully.
    """
    proc = process_manager.get_process(agent_id)
    if proc is None:
        logger.warning("Cannot deliver message: agent %s not found", agent_id)
        return False

    if not proc.is_alive():
        logger.warning("Cannot deliver message: agent %s is dead", agent_id)
        return False

    # Interrupt if busy
    if interrupt_if_busy:
        prompt_returned = process_manager.interrupt_agent(agent_id)
        if not prompt_returned:
            logger.warning(
                "Agent %s did not return to prompt after interrupt; message delivery may fail",
                agent_id,
            )

    # Long messages: write to file
    if len(message) > LONG_MESSAGE_THRESHOLD:
        return _deliver_via_file(process_manager, agent_id, message, message_dir)

    # Short messages: send directly
    return process_manager.send_keys(agent_id, message, enter=True)


def _deliver_via_file(
    process_manager: ProcessManager,
    agent_id: str,
    message: str,
    message_dir: Path | None = None,
) -> bool:
    """Write message to a temp file and send the path to the agent."""
    if message_dir is None:
        message_dir = Path(tempfile.gettempdir()) / "phalanx_messages"
    message_dir.mkdir(parents=True, exist_ok=True)

    msg_file = message_dir / f"msg_{agent_id}_{hash(message) & 0xFFFFFFFF:08x}.txt"
    msg_file.write_text(message, encoding="utf-8")

    delivery_text = f"Read the message at: {msg_file}"
    return process_manager.send_keys(agent_id, delivery_text, enter=True)
