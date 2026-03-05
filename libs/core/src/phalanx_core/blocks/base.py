"""
BaseBlock abstract interface for workflow blocks.
"""

from abc import ABC, abstractmethod
from phalanx_core.state import WorkflowState


class BaseBlock(ABC):
    """
    Abstract base for workflow blocks. All concrete blocks must implement execute().

    Constructor contract: All subclasses MUST accept block_id as first parameter.
    """

    def __init__(self, block_id: str):
        """
        Args:
            block_id: Unique identifier for this block instance within a blueprint.
                     Used as the key in state.results.

        Raises:
            ValueError: If block_id is empty string.
        """
        if not block_id:
            raise ValueError("block_id cannot be empty")
        self.block_id = block_id

    @abstractmethod
    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Execute this block's logic using the provided state.

        Args:
            state: Current workflow state. MUST NOT be mutated directly.

        Returns:
            New WorkflowState with updated results, messages, or shared_memory.
            MUST include this block's output in state.results[self.block_id].

        Raises:
            ValueError: If required inputs are missing from state.
            Exception: If execution fails (propagates to Workflow.run() caller).
        """
        pass
