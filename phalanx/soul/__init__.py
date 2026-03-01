"""Soul files: templates for team lead, worker, and main agent skill."""

from .loader import (
    load_soul,
    load_team_lead_soul,
    load_worker_soul,
    load_skill,
    write_soul_to_temp,
)

__all__ = [
    "load_soul",
    "load_team_lead_soul",
    "load_worker_soul",
    "load_skill",
    "write_soul_to_temp",
]
