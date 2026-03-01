"""Backend auto-detection and registry."""

from __future__ import annotations

from .base import AgentBackend
from .cursor import CursorBackend
from .claude import ClaudeBackend
from .gemini import GeminiBackend
from .codex import CodexBackend

DETECTION_ORDER = ["cursor", "claude", "gemini", "codex"]

_BACKENDS: dict[str, type[AgentBackend]] = {
    "cursor": CursorBackend,
    "claude": ClaudeBackend,
    "gemini": GeminiBackend,
    "codex": CodexBackend,
}


def get_backend(name: str) -> AgentBackend:
    """Get a backend instance by name. Raises KeyError if unknown."""
    cls = _BACKENDS[name]
    return cls()


def list_backends() -> list[str]:
    return list(_BACKENDS.keys())


def detect_available() -> list[str]:
    """Return names of all installed backends, in detection order."""
    available = []
    for name in DETECTION_ORDER:
        backend = get_backend(name)
        if backend.detect():
            available.append(name)
    return available


def detect_default() -> str:
    """Return the first available backend. Raises RuntimeError if none found."""
    available = detect_available()
    if not available:
        raise RuntimeError(
            "No agent CLI found. Install one of: cursor (agent), claude, gemini, codex"
        )
    return available[0]
