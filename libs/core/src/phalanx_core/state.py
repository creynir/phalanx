"""
WorkflowState data model for workflow execution context.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from phalanx_core.primitives import Task


class WorkflowState(BaseModel):
    """
    Workflow execution context. Blocks receive state, return updated state.

    Best Practice: Use model_copy(update={...}) to create new state instances
    rather than mutating fields directly.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Conversation history. Format: [{'role': 'system', 'content': '...'}]",
    )
    shared_memory: Dict[str, Any] = Field(
        default_factory=dict,
        description="Cross-block shared data. Keys: arbitrary strings. Values: JSON-serializable.",
    )
    current_task: Optional[Task] = Field(
        default=None,
        description="Active task being processed. Blocks read this to determine their work.",
    )
    results: Dict[str, str] = Field(
        default_factory=dict,
        description="Block outputs keyed by block_id. Values are string outputs or JSON.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Workflow-level tracking: execution_start_time, blueprint_name, etc.",
    )
