"""
Concrete block implementations for workflow composition.
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional, Union

from phalanx_core.blocks.base import BaseBlock
from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Soul, Task
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


class FanOutBlock(BaseBlock):
    """
    Executes the current task with multiple agents in parallel.

    Typical Use: Gather diverse perspectives (3 reviewers critique a proposal).
    Output Format: JSON list [{"soul_id": "...", "output": "..."}, ...]
    """

    def __init__(self, block_id: str, souls: List[Soul], runner: PhalanxTeamRunner):
        """
        Args:
            block_id: Unique block identifier.
            souls: List of agents to run in parallel (must be non-empty).
            runner: Execution engine for running tasks.

        Raises:
            ValueError: If block_id is empty or souls list is empty.
        """
        super().__init__(block_id)
        if not souls:
            raise ValueError(f"FanOutBlock {block_id}: souls list cannot be empty")
        self.souls = souls
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Execute state.current_task in parallel across all souls.

        Args:
            state: Must have state.current_task set.

        Returns:
            New state with:
            - results[block_id] = JSON list of {"soul_id": str, "output": str}
            - messages appended with fanout summary

        Raises:
            ValueError: If state.current_task is None.
            Exception: If ANY soul execution fails, entire block fails (all-or-nothing).
        """
        if state.current_task is None:
            raise ValueError(f"FanOutBlock {self.block_id}: state.current_task is None")

        # Execute all souls in parallel (preserves order)
        tasks = [self.runner.execute_task(state.current_task, soul) for soul in self.souls]
        results = await asyncio.gather(*tasks)  # Raises on first failure

        # Aggregate outputs as JSON
        outputs = [{"soul_id": result.soul_id, "output": result.output} for result in results]

        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: json.dumps(outputs, indent=2)},
                "messages": state.messages
                + [
                    {
                        "role": "system",
                        "content": f"[Block {self.block_id}] FanOut completed with {len(self.souls)} agents",
                    }
                ],
            }
        )


class SynthesizeBlock(BaseBlock):
    """
    Reads outputs from multiple input blocks and synthesizes them into a cohesive result.

    Typical Use: Combine research + code + review into final report.
    """

    def __init__(
        self,
        block_id: str,
        input_block_ids: List[str],
        synthesizer_soul: Soul,
        runner: PhalanxTeamRunner,
    ):
        """
        Args:
            block_id: Unique block identifier.
            input_block_ids: Block IDs whose outputs to synthesize (must be non-empty).
            synthesizer_soul: Agent that performs synthesis.
            runner: Execution engine for running tasks.

        Raises:
            ValueError: If block_id is empty or input_block_ids is empty.
        """
        super().__init__(block_id)
        if not input_block_ids:
            raise ValueError(f"SynthesizeBlock {block_id}: input_block_ids cannot be empty")
        self.input_block_ids = input_block_ids
        self.synthesizer_soul = synthesizer_soul
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Read inputs, construct synthesis task, execute with synthesizer.

        Args:
            state: Must have all input_block_ids present in state.results.

        Returns:
            New state with:
            - results[block_id] = synthesized output string
            - messages appended with synthesis summary

        Raises:
            ValueError: If any input_block_id missing from state.results.
        """
        # Validate all inputs exist
        missing = [bid for bid in self.input_block_ids if bid not in state.results]
        if missing:
            raise ValueError(
                f"SynthesizeBlock {self.block_id}: missing inputs: {missing}. "
                f"Available: {list(state.results.keys())}"
            )

        # Gather inputs
        combined_outputs = "\n\n".join(
            [f"=== Output from {bid} ===\n{state.results[bid]}" for bid in self.input_block_ids]
        )

        # Construct synthesis task
        synthesis_instruction = (
            "Synthesize the following outputs into a cohesive, unified result. "
            "Identify common themes, resolve conflicts, and provide a comprehensive summary.\n\n"
            f"{combined_outputs}"
        )
        synthesis_task = Task(id=f"{self.block_id}_synthesis", instruction=synthesis_instruction)

        # Execute synthesis
        result = await self.runner.execute_task(synthesis_task, self.synthesizer_soul)

        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: result.output},
                "messages": state.messages
                + [
                    {
                        "role": "system",
                        "content": f"[Block {self.block_id}] Synthesized {len(self.input_block_ids)} inputs",
                    }
                ],
            }
        )


class DebateBlock(BaseBlock):
    """
    Runs iterative debate between two agents, storing transcript and conclusion.

    Typical Use: Adversarial review (agent A proposes, agent B critiques, iterate).
    Output Format: JSON transcript + conclusion in shared_memory.
    """

    def __init__(
        self,
        block_id: str,
        soul_a: Soul,
        soul_b: Soul,
        iterations: int,
        runner: PhalanxTeamRunner,
    ):
        """
        Args:
            block_id: Unique block identifier.
            soul_a: First debater (starts each round).
            soul_b: Second debater (responds to soul_a).
            iterations: Number of debate rounds (must be >= 1).
            runner: Execution engine for running tasks.

        Raises:
            ValueError: If block_id is empty or iterations < 1.
        """
        super().__init__(block_id)
        if iterations < 1:
            raise ValueError(f"DebateBlock {block_id}: iterations must be >= 1, got {iterations}")
        self.soul_a = soul_a
        self.soul_b = soul_b
        self.iterations = iterations
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Run debate for N iterations, alternating between soul_a and soul_b.

        Args:
            state: Must have state.current_task set (the debate topic).

        Returns:
            New state with:
            - results[block_id] = JSON transcript: [{"round": 1, "soul_a": "...", "soul_b": "..."}, ...]
            - shared_memory[f"{block_id}_conclusion"] = final soul_b response
            - messages appended with debate summary

        Raises:
            ValueError: If state.current_task is None.
        """
        if state.current_task is None:
            raise ValueError(f"DebateBlock {self.block_id}: state.current_task is None")

        transcript: List[Dict[str, any]] = []
        previous_b_output: str = ""

        for round_num in range(1, self.iterations + 1):
            # Soul A responds (includes previous B output if available)
            task_a_context = (
                f"Previous response from {self.soul_b.role}: {previous_b_output}"
                if previous_b_output
                else None
            )
            task_a = Task(
                id=f"{self.block_id}_round{round_num}_a",
                instruction=state.current_task.instruction,
                context=task_a_context,
            )
            result_a = await self.runner.execute_task(task_a, self.soul_a)

            # Soul B responds to A's output
            task_b = Task(
                id=f"{self.block_id}_round{round_num}_b",
                instruction=state.current_task.instruction,
                context=f"Response from {self.soul_a.role}: {result_a.output}",
            )
            result_b = await self.runner.execute_task(task_b, self.soul_b)

            transcript.append(
                {"round": round_num, "soul_a": result_a.output, "soul_b": result_b.output}
            )
            previous_b_output = result_b.output

        # Final conclusion is last soul_b response
        conclusion = transcript[-1]["soul_b"]

        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: json.dumps(transcript, indent=2)},
                "shared_memory": {
                    **state.shared_memory,
                    f"{self.block_id}_conclusion": conclusion,
                },
                "messages": state.messages
                + [
                    {
                        "role": "system",
                        "content": f"[Block {self.block_id}] Debate completed: {self.iterations} rounds",
                    }
                ],
            }
        )


class RouterBlock(BaseBlock):
    """
    Evaluate routing condition using Soul (LLM) or Callable (function).

    Typical Use: Decision-making blocks that route workflow based on conditions.
    Example (Soul): LLM evaluates proposal and returns "approved" or "rejected"
    Example (Callable): Function checks state and returns routing decision
    """

    def __init__(
        self,
        block_id: str,
        condition_evaluator: Union[Soul, Callable[[WorkflowState], str]],
        runner: Optional[PhalanxTeamRunner] = None,
    ):
        """
        Args:
            block_id: Unique block identifier.
            condition_evaluator: Either a Soul (LLM evaluates) or Callable (function evaluates).
            runner: Required if condition_evaluator is Soul, optional otherwise.

        Raises:
            ValueError: If block_id is empty (from BaseBlock).
            ValueError: If condition_evaluator is Soul but runner is None.
        """
        super().__init__(block_id)

        # Validate runner requirement for Soul evaluator
        if isinstance(condition_evaluator, Soul) and runner is None:
            raise ValueError(
                f"RouterBlock {block_id}: runner is required when condition_evaluator is Soul"
            )

        self.condition_evaluator = condition_evaluator
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Evaluate routing condition and store decision.

        Args:
            state: If condition_evaluator is Soul, must have state.current_task set.

        Returns:
            New state with:
            - results[block_id] = decision string (e.g., "approved", "rejected")
            - metadata[f"{block_id}_decision"] = decision string (duplicate for downstream access)
            - messages appended with routing decision summary

        Raises:
            ValueError: If condition_evaluator is Soul but current_task is None.
        """
        # Step 1: Evaluate condition based on type
        if isinstance(self.condition_evaluator, Soul):
            # Soul-based evaluation (LLM decides)
            if state.current_task is None:
                raise ValueError(
                    f"RouterBlock {self.block_id}: state.current_task is None (required for Soul evaluator)"
                )

            # Execute routing task with Soul (runner guaranteed non-None by constructor validation)
            assert self.runner is not None  # For mypy: validated in __init__
            result = await self.runner.execute_task(state.current_task, self.condition_evaluator)
            decision = result.output.strip()
        else:
            # Callable-based evaluation (function decides)
            decision = self.condition_evaluator(state)

        # Step 2: Return updated state with decision
        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: decision},
                "metadata": {
                    **state.metadata,
                    f"{self.block_id}_decision": decision,
                },
                "messages": state.messages
                + [
                    {
                        "role": "system",
                        "content": f"[Block {self.block_id}] RouterBlock decision: {decision}",
                    }
                ],
            }
        )


class AdvisorBlock(BaseBlock):
    """
    Analyze failure context from shared_memory and produce recommendations.

    Typical Use: After RetryBlock exhausts retries, analyze errors and recommend fixes.
    Example: AdvisorBlock reads retry_errors and produces actionable recommendation.
    """

    def __init__(
        self,
        block_id: str,
        failure_context_keys: List[str],
        advisor_soul: Soul,
        runner: PhalanxTeamRunner,
    ):
        """
        Args:
            block_id: Unique block identifier.
            failure_context_keys: Keys to read from state.shared_memory for analysis.
            advisor_soul: Agent that performs failure analysis.
            runner: Execution engine for running tasks.

        Raises:
            ValueError: If block_id is empty or failure_context_keys is empty.
        """
        super().__init__(block_id)
        if not failure_context_keys:
            raise ValueError(f"AdvisorBlock {block_id}: failure_context_keys cannot be empty")
        self.failure_context_keys = failure_context_keys
        self.advisor_soul = advisor_soul
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Analyze failure context and produce recommendations.

        Args:
            state: Must have all failure_context_keys present in shared_memory.

        Returns:
            New state with:
            - results[block_id] = recommendation text
            - shared_memory[f"{block_id}_recommendation"] = recommendation text
            - messages appended with advisor summary

        Raises:
            ValueError: If any failure_context_key missing from state.shared_memory.
        """
        # Step 1: Validate all context keys exist
        missing_keys = [key for key in self.failure_context_keys if key not in state.shared_memory]
        if missing_keys:
            raise ValueError(
                f"AdvisorBlock {self.block_id}: missing failure context keys: {missing_keys}. "
                f"Available keys: {list(state.shared_memory.keys())}"
            )

        # Step 2: Gather error context
        error_contexts = []
        for key in self.failure_context_keys:
            context_value = state.shared_memory[key]
            # Handle both list and string values
            if isinstance(context_value, list):
                formatted = "\n".join([f"  - {item}" for item in context_value])
            else:
                formatted = str(context_value)
            error_contexts.append(f"Context from '{key}':\n{formatted}")

        combined_context = "\n\n".join(error_contexts)

        # Step 3: Construct analysis task
        analysis_instruction = f"""You are analyzing a workflow failure. Review the error context below and provide:
1. Root cause analysis
2. Recommended remediation steps
3. Prevention strategies for future runs

Error Context:
{combined_context}

Provide your analysis and recommendations in a structured format."""

        analysis_task = Task(id=f"{self.block_id}_analysis", instruction=analysis_instruction)

        # Step 4: Execute analysis
        result = await self.runner.execute_task(analysis_task, self.advisor_soul)

        # Step 5: Return updated state
        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: result.output},
                "shared_memory": {
                    **state.shared_memory,
                    f"{self.block_id}_recommendation": result.output,
                },
                "messages": state.messages
                + [
                    {
                        "role": "system",
                        "content": f"[Block {self.block_id}] AdvisorBlock analyzed {len(self.failure_context_keys)} context(s)",
                    }
                ],
            }
        )
