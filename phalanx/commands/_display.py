"""Shared display helpers for CLI commands."""

_USER_STATUS = {
    "completed": "stopped",
    "suspended": "stopped",
    "dead": "stopped",
    "completing": "running",
}


def display_status(status: str) -> str:
    """Map internal agent/team status to user-visible label."""
    return _USER_STATUS.get(status, status)
