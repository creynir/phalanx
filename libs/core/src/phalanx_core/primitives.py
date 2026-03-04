"""
Core primitives for Phalanx Agent OS.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Soul(BaseModel):
    """
    Represents an agent's persona, capabilities, and expected output schema.
    """

    id: str = Field(..., description="Unique identifier for the soul (e.g., 'researcher_v1')")
    role: str = Field(..., description="The role of the agent (e.g., 'Senior Researcher')")
    system_prompt: str = Field(
        ..., description="The system instructions defining the agent's behavior and constraints"
    )
    tools: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Optional list of tools the agent can use"
    )


class Task(BaseModel):
    """
    Represents an isolated instruction for an agent to execute.
    """

    id: str = Field(..., description="Unique identifier for the task")
    instruction: str = Field(..., description="The main instruction or prompt for the task")
    context: Optional[str] = Field(
        default=None, description="Additional context or background information for the task"
    )
