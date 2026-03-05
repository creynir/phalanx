"""
Pydantic schema models for Phalanx YAML workflow files.
No imports from phalanx_core — pure data definition layer.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SoulDef(BaseModel):
    """Soul definition as expressed in the YAML souls: section."""

    id: str
    role: str
    system_prompt: str
    tools: Optional[List[Dict[str, Any]]] = None


class TaskDef(BaseModel):
    """Task definition as expressed in the YAML tasks: section."""

    id: str
    instruction: str
    context: Optional[str] = None


class PhalanxTaskFile(BaseModel):
    """
    Root model for a Phalanx task YAML file.
    Uses wrapper format: version + task.
    """

    version: str = "1.0"
    task: TaskDef  # required — no default; Pydantic raises ValidationError if absent


class BlockDef(BaseModel):
    """
    Block definition. `type` is the only required field.
    All other fields are optional; extra fields are allowed for custom block configs.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    # Common optional fields — present on specific block types
    soul_ref: Optional[str] = None  # LinearBlock, SynthesizeBlock, RouterBlock, etc.
    soul_refs: Optional[List[str]] = None  # FanOutBlock, MessageBusBlock
    soul_a_ref: Optional[str] = None  # DebateBlock
    soul_b_ref: Optional[str] = None  # DebateBlock
    input_block_ids: Optional[List[str]] = None  # SynthesizeBlock
    inner_block_ref: Optional[str] = None  # RetryBlock
    failure_context_keys: Optional[List[str]] = None  # TeamLeadBlock
    condition_ref: Optional[str] = None  # RouterBlock (Callable path, future use)
    iterations: Optional[int] = None  # DebateBlock, MessageBusBlock
    max_retries: Optional[int] = None  # RetryBlock


class TransitionDef(BaseModel):
    """Plain (single-path) transition: from -> to. to=None means terminal block."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")  # 'from' is a Python keyword; alias maps YAML 'from:' key
    to: Optional[str] = None


class ConditionalTransitionDef(BaseModel):
    """
    Conditional (multi-path) transition. Extra fields are decision_key -> target_block_id.

    YAML structure:
        conditional_transitions:
          - from: router_block
            approved: approve_block
            rejected: reject_block
            default: reject_block   # optional fallback
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    from_: str = Field(alias="from")
    default: Optional[str] = None
    # Extra fields accessed via model_extra: {decision_key: target_block_id, ...}


class WorkflowDef(BaseModel):
    """Top-level workflow graph definition."""

    name: str
    entry: str  # required — no default
    transitions: List[TransitionDef] = Field(default_factory=list)
    conditional_transitions: List[ConditionalTransitionDef] = Field(default_factory=list)


class PhalanxWorkflowFile(BaseModel):
    """
    Root model for a Phalanx .yaml workflow file.
    'workflow' is the only required top-level key — all others have defaults.
    """

    version: str = "1.0"
    config: Dict[str, Any] = Field(default_factory=dict)
    souls: Dict[str, SoulDef] = Field(default_factory=dict)
    blocks: Dict[str, BlockDef] = Field(default_factory=dict)
    workflow: WorkflowDef  # required — no default; Pydantic raises ValidationError if absent
