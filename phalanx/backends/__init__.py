"""Agent backend adapters (Cursor, Claude, Gemini, Codex)."""

from .base import AgentBackend
from .registry import get_backend, list_backends

__all__ = ["AgentBackend", "get_backend", "list_backends"]
