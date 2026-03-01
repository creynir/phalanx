"""Config-driven model routing: role + backend → model name."""

from __future__ import annotations

from typing import Any


def resolve_model(backend: str, role: str, config: dict[str, Any]) -> str:
    """Look up the model for a given backend and role from config.

    Fallback: config[backend][role] → config[backend]["default"].
    Raises KeyError if the backend section is missing from config.
    """
    models = config["models"][backend]
    return models.get(role, models["default"])
