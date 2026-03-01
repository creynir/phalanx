"""Backend registry — auto-detection and lookup."""

from __future__ import annotations

import shutil

from .base import AgentBackend
from .claude import ClaudeBackend
from .codex import CodexBackend
from .cursor import CursorBackend
from .gemini import GeminiBackend

_BACKENDS: dict[str, type[AgentBackend]] = {
    "cursor": CursorBackend,
    "claude": ClaudeBackend,
    "gemini": GeminiBackend,
    "codex": CodexBackend,
}


def get_backend(name: str) -> AgentBackend:
    """Get a backend by name."""
    cls = _BACKENDS.get(name.lower())
    if not cls:
        raise ValueError(f"Unknown backend '{name}'. Available: {', '.join(_BACKENDS)}")
    return cls()


def list_backends() -> list[str]:
    """List all registered backend names."""
    return list(_BACKENDS.keys())


def detect_backend() -> AgentBackend | None:
    """Auto-detect an available backend by checking PATH."""
    for name in ("cursor", "claude", "gemini", "codex"):
        if shutil.which(name):
            return get_backend(name)
    return None
