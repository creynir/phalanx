"""phalanx.commands — v2 CLI command groups."""
from __future__ import annotations

from phalanx.commands.agent import agent_group
from phalanx.commands.feed import feed_group
from phalanx.commands.lock import lock_group
from phalanx.commands.msg import msg_group
from phalanx.commands.team import team_group

__all__ = [
    "agent_group",
    "feed_group",
    "lock_group",
    "msg_group",
    "team_group",
]
