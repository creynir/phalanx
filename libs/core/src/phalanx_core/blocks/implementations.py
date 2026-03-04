"""
Concrete block implementations for workflow composition.
"""

from phalanx_core.blocks.base import BaseBlock
from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Soul
from phalanx_core.runner import PhalanxTeamRunner


class LinearBlock(BaseBlock):
    """
    Executes the current task with a single agent.

    Typical Use: Sequential processing where one agent completes a task.
    Example: Research block → writes research report to results.
    """

    def __init__(self, block_id: str, soul: Soul, runner: PhalanxTeamRunner):
        """
        Args:
            block_id: Unique block identifier.
            soul: The agent that will execute the task.
            runner: Execution engine for running tasks.

        Raises:
            ValueError: If block_id is empty (from BaseBlock).
        """
        super().__init__(block_id)
        self.soul = soul
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Execute state.current_task using self.soul.

        Args:
            state: Must have state.current_task set.

        Returns:
            New state with:
            - results[block_id] = execution output string
            - messages appended with execution summary

        Raises:
            ValueError: If state.current_task is None.
        """
        if state.current_task is None:
            raise ValueError(f"LinearBlock {self.block_id}: state.current_task is None")

        result = await self.runner.execute_task(state.current_task, self.soul)

        # Truncate output for message log (prevent state size explosion)
        truncated = result.output[:200] + "..." if len(result.output) > 200 else result.output

        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: result.output},
                "messages": state.messages
                + [
                    {"role": "system", "content": f"[Block {self.block_id}] Completed: {truncated}"}
                ],
            }
        )
