"""Team management: create, stop, status, spawn."""

from .create import create_team, parse_agents_spec
from .orchestrator import get_team_status, stop_team, get_team_result

__all__ = [
    "create_team",
    "parse_agents_spec",
    "get_team_status",
    "stop_team",
    "get_team_result",
]
