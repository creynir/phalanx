"""
Core primitives for Phalanx Agent OS.
"""

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from phalanx_core.blocks.base import BaseBlock
    from phalanx_core.blueprint import Blueprint

from phalanx_core.state import WorkflowState


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


class Step:
    """
    Wrapper for BaseBlock with pre/post hook execution.

    Use Case: Add logging, validation, or state transformation around blocks.
    Example: pre_hook = log start time, post_hook = log end time + duration.

    Note: Hooks must be synchronous. For async operations, use a block instead.
    """

    def __init__(
        self,
        block: "BaseBlock",
        pre_hook: Optional[Callable[[WorkflowState], WorkflowState]] = None,
        post_hook: Optional[Callable[[WorkflowState], WorkflowState]] = None,
    ) -> None:
        """
        Args:
            block: The block to wrap.
            pre_hook: Optional function to run before block execution.
                     Receives state, returns modified state (or same state).
                     MUST be synchronous (not async).
            post_hook: Optional function to run after block execution.
                      Receives state (output from block), returns modified state.
                      MUST be synchronous (not async).
        """
        self.block = block
        self.pre_hook = pre_hook
        self.post_hook = post_hook

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Execute pre_hook → block → post_hook in sequence.

        Args:
            state: Initial workflow state.

        Returns:
            Final state after all three phases (or fewer if hooks are None).

        Raises:
            Exception: Propagates any exception from hooks or block.
        """
        # Phase 1: Pre-hook (optional)
        if self.pre_hook is not None:
            state = self.pre_hook(state)

        # Phase 2: Block execution (required)
        state = await self.block.execute(state)

        # Phase 3: Post-hook (optional)
        if self.post_hook is not None:
            state = self.post_hook(state)

        return state


class Skill:
    """
    Blueprint wrapper with metadata for reusable workflow components.

    Use Case: Package common Blueprint patterns (e.g., "research_v1", "code_review_v2")
    for reuse across multiple workflows without Blueprint boilerplate.
    """

    def __init__(
        self,
        skill_id: str,
        description: str,
        blueprint: "Blueprint",  # Forward reference to avoid circular import
    ) -> None:
        """
        Args:
            skill_id: Unique identifier for this skill (e.g., "research_pipeline_v1").
            description: Human-readable description of what this skill does.
            blueprint: The Blueprint that implements this skill.

        Raises:
            ValueError: If skill_id or description is empty.
        """
        if not skill_id:
            raise ValueError("Skill skill_id cannot be empty")
        if not description:
            raise ValueError("Skill description cannot be empty")

        self.skill_id = skill_id
        self.description = description
        self.blueprint = blueprint

    async def run(self, state: "WorkflowState") -> "WorkflowState":
        """
        Execute the wrapped blueprint.

        Args:
            state: Initial workflow state.

        Returns:
            Final state after blueprint execution, with skill metadata cleaned.

        Raises:
            ValueError: If blueprint is invalid (propagates from blueprint.run()).
            Exception: If any block in blueprint fails (propagates from blueprint.run()).
        """
        # Import here to avoid circular import at module load time

        # Step 1: Add skill metadata to state
        state = state.model_copy(
            update={
                "metadata": {
                    **state.metadata,
                    "active_skill_id": self.skill_id,
                    "active_skill_description": self.description,
                }
            }
        )

        # Step 2: Delegate to blueprint
        result_state = await self.blueprint.run(state)

        # Step 3: Clean up active skill metadata (skill execution complete)
        result_state = result_state.model_copy(
            update={
                "metadata": {
                    k: v
                    for k, v in result_state.metadata.items()
                    if k not in ["active_skill_id", "active_skill_description"]
                }
            }
        )

        return result_state
