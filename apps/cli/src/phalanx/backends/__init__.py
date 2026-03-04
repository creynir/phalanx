"""Agent backend adapters (Cursor, Claude, Gemini, Codex)."""

from .base import AgentBackend
from .registry import get_backend

__all__ = ["AgentBackend", "get_backend"]
