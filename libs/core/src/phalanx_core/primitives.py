"""
Core primitives for Phalanx Agent OS.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class Soul(BaseModel):
    """Agent definition with role and system prompt."""

    id: str
    role: str
    system_prompt: str
    tools: Optional[List[Dict[str, Any]]] = None


class Task(BaseModel):
    """Work unit for agent execution."""

    id: str
    instruction: str
    context: Optional[str] = None
