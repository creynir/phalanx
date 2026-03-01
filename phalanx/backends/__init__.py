"""Backend adapters for agent CLIs."""

from .base import AgentBackend
from .registry import detect_available, detect_default, get_backend, list_backends
from .model_router import resolve_model

__all__ = [
    "AgentBackend",
    "detect_available",
    "detect_default",
    "get_backend",
    "list_backends",
    "resolve_model",
]
