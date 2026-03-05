"""
Concrete block implementations for workflow composition.
"""

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional, Union

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

        transcript: List[Dict[str, Any]] = []
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


class RetryBlock(BaseBlock):
    """
    Wrap any BaseBlock with retry logic on exceptions.

    Typical Use: Wrap flaky API blocks or unreliable operations.
    Example: RetryBlock wraps APICallBlock, retries on ConnectionError.
    """

    def __init__(
        self,
        block_id: str,
        inner_block: BaseBlock,
        max_retries: int = 3,
        provide_error_context: bool = False,
    ) -> None:
        """
        Args:
            block_id: Unique identifier for this block instance.
            inner_block: The block to wrap with retry logic.
            max_retries: Maximum number of retries after initial attempt (default: 3).
                        Total attempts = 1 initial + max_retries.
            provide_error_context: If True, store error messages in shared_memory.

        Raises:
            ValueError: If block_id is empty (from BaseBlock).
            ValueError: If max_retries < 0.
        """
        super().__init__(block_id)
        if max_retries < 0:
            raise ValueError(f"RetryBlock {block_id}: max_retries must be >= 0, got {max_retries}")
        self.inner_block = inner_block
        self.max_retries = max_retries
        self.provide_error_context = provide_error_context

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Execute inner block with retry logic on exceptions.

        Args:
            state: Passed to inner_block.execute().

        Returns:
            New state with:
            - results[block_id] = results[inner_block.block_id] (if success)
            - shared_memory[f"{block_id}_retry_errors"] = List[str] (if provide_error_context=True)
            - messages appended with retry summary

        Raises:
            Exception: If all retries exhausted, raises the last exception from inner_block.
        """
        errors: List[str] = []
        attempts = 0  # Starts at 0, will increment to 1, 2, 3, ...
        last_exception: Optional[Exception] = None

        # Total attempts = 1 initial + max_retries retries
        for attempt_num in range(self.max_retries + 1):
            attempts += 1  # attempts now = 1, 2, 3, ... up to max_retries+1

            try:
                # Attempt execution
                result_state = await self.inner_block.execute(state)

                # Success! Store inner block's result under THIS block's ID
                final_state = result_state.model_copy(
                    update={
                        "results": {
                            **result_state.results,
                            self.block_id: result_state.results.get(self.inner_block.block_id, ""),
                        },
                        "messages": result_state.messages
                        + [
                            {
                                "role": "system",
                                "content": f"[Block {self.block_id}] RetryBlock succeeded after {attempts} attempt(s)",
                            }
                        ],
                    }
                )

                # Optionally store error context even on success (shows what was overcome)
                if self.provide_error_context and errors:
                    final_state = final_state.model_copy(
                        update={
                            "shared_memory": {
                                **final_state.shared_memory,
                                f"{self.block_id}_retry_errors": errors,
                            }
                        }
                    )

                return final_state

            except Exception as e:
                last_exception = e
                error_msg = (
                    f"Attempt {attempts}/{self.max_retries + 1}: {type(e).__name__}: {str(e)}"
                )
                errors.append(error_msg)

                # If this was the last attempt, don't continue loop
                if attempt_num == self.max_retries:
                    break
                # Otherwise, continue to next retry

        # All retries exhausted - store error context and re-raise
        if self.provide_error_context:
            state = state.model_copy(
                update={
                    "shared_memory": {
                        **state.shared_memory,
                        f"{self.block_id}_retry_errors": errors,
                    }
                }
            )

        # Re-raise last exception
        if last_exception is not None:
            raise last_exception
        else:
            # This should never happen, but satisfy type checker
            raise RuntimeError(f"RetryBlock {self.block_id}: unexpected error state")


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


class ReplannerBlock(BaseBlock):
    """
    Generate alternative execution plan using LLM, parse into structured steps.

    Typical Use: After workflow failure, generate new plan with structured steps.
    Example: ReplannerBlock reads current task and failure context, produces plan + JSON steps.
    """

    def __init__(
        self,
        block_id: str,
        planner_soul: Soul,
        runner: PhalanxTeamRunner,
    ):
        """
        Args:
            block_id: Unique block identifier.
            planner_soul: Agent that generates execution plans.
            runner: Execution engine for running tasks.

        Raises:
            ValueError: If block_id is empty (from BaseBlock).
        """
        super().__init__(block_id)
        self.planner_soul = planner_soul
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Generate alternative execution plan based on current context.

        Args:
            state: Must have state.current_task set. Optionally reads failure context from shared_memory.

        Returns:
            New state with:
            - results[block_id] = text plan from LLM
            - metadata[f"{block_id}_new_steps"] = List[Dict[str, str]] with keys: step_id, description
            - messages appended with replanner summary

        Raises:
            ValueError: If state.current_task is None.
        """
        # Step 1: Validate current_task
        if state.current_task is None:
            raise ValueError(f"ReplannerBlock {self.block_id}: state.current_task is None")

        # Step 2: Gather context (current task + any failure info in shared_memory)
        context_parts = [f"Original Goal: {state.current_task.instruction}"]

        # Check for common failure context keys
        if f"{self.block_id}_previous_errors" in state.shared_memory:
            context_parts.append(
                f"Previous Errors:\n{state.shared_memory[f'{self.block_id}_previous_errors']}"
            )

        combined_context = "\n\n".join(context_parts)

        # Step 3: Construct planning task
        planning_instruction = f"""You are a workflow planner. Given the context below, create a detailed execution plan.

{combined_context}

Provide your plan as a numbered list where each step follows this format:
<step_number>. <step_id>: <description>

Example:
1. research_phase: Gather requirements and analyze constraints
2. design_phase: Create technical architecture
3. implementation_phase: Implement core features

Your plan:"""

        planning_task = Task(id=f"{self.block_id}_planning", instruction=planning_instruction)

        # Step 4: Execute planning task
        result = await self.runner.execute_task(planning_task, self.planner_soul)
        text_plan = result.output

        # Step 5: Parse plan to extract structured steps
        # Regex pattern: ^\d+\.\s+([^:]+):\s+(.+)$
        # Matches: "1. step_id: description"
        step_pattern = re.compile(r"^\d+\.\s+([^:]+):\s+(.+)$", re.MULTILINE)
        matches = step_pattern.findall(text_plan)

        structured_steps: List[Dict[str, str]] = []
        if matches:
            # Successfully parsed structured format
            for step_id, description in matches:
                structured_steps.append(
                    {"step_id": step_id.strip(), "description": description.strip()}
                )
        else:
            # Fallback: LLM didn't follow format, create single generic step
            structured_steps = [
                {
                    "step_id": "replanned_execution",
                    "description": text_plan[:200] + "..." if len(text_plan) > 200 else text_plan,
                }
            ]

        # Step 6: Return updated state
        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: text_plan},
                "metadata": {
                    **state.metadata,
                    f"{self.block_id}_new_steps": structured_steps,
                },
                "messages": state.messages
                + [
                    {
                        "role": "system",
                        "content": f"[Block {self.block_id}] ReplannerBlock generated {len(structured_steps)} step(s)",
                    }
                ],
            }
        )


class MessageBusBlock(BaseBlock):
    """
    Orchestrate N-agent round-robin message exchange with structured transcript output.

    Typical Use: Multi-agent brainstorming with context passing between agents.
    Example: 4 agents collaborate for 3 rounds, each agent sees prior contributions in their round.
    Output Format: JSON transcript with rounds and contributions, consensus in shared_memory.
    """

    def __init__(
        self,
        block_id: str,
        souls: List[Soul],
        iterations: int,
        runner: PhalanxTeamRunner,
    ):
        """
        Args:
            block_id: Unique block identifier.
            souls: List of agents participating in message exchange (must be non-empty).
            iterations: Number of rounds to execute (must be >= 1).
            runner: Execution engine for running tasks.

        Raises:
            ValueError: If block_id is empty (from BaseBlock).
            ValueError: If souls list is empty.
            ValueError: If iterations < 1.
        """
        super().__init__(block_id)
        if not souls:
            raise ValueError(f"MessageBusBlock {block_id}: souls list cannot be empty")
        if iterations < 1:
            raise ValueError(
                f"MessageBusBlock {block_id}: iterations must be >= 1, got {iterations}"
            )
        self.souls = souls
        self.iterations = iterations
        self.runner = runner

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """
        Execute N-agent round-robin message exchange.

        Args:
            state: Must have state.current_task set (the discussion topic).

        Returns:
            New state with:
            - results[block_id] = JSON transcript: [{"round": int, "contributions": [{"soul_id": str, "output": str}]}]
            - shared_memory[f"{block_id}_consensus"] = final agent output from last round
            - messages appended with message bus summary

        Raises:
            ValueError: If state.current_task is None.
        """
        # Step 1: Validate current_task
        if state.current_task is None:
            raise ValueError(f"MessageBusBlock {self.block_id}: state.current_task is None")

        # Step 2: Initialize transcript
        transcript: List[Dict[str, Any]] = []

        # Step 3: Execute iterations
        for round_num in range(1, self.iterations + 1):
            round_contributions: List[Dict[str, str]] = []

            # Step 4: Sequential contributions within round
            for soul in self.souls:
                # Context passing mechanism
                # Construct task by appending formatted contributions to current_task.instruction
                if round_contributions:
                    # Format prior contributions in THIS round
                    formatted_context = "\n\n".join(
                        [f"[{c['soul_id']}]: {c['output']}" for c in round_contributions]
                    )
                    context_str = f"Prior contributions in this round:\n{formatted_context}"
                else:
                    context_str = None

                # Create task with context
                task = Task(
                    id=f"{self.block_id}_r{round_num}_{soul.id}",
                    instruction=state.current_task.instruction,
                    context=context_str,
                )

                # Execute task
                result = await self.runner.execute_task(task, soul)

                # Record contribution
                round_contributions.append({"soul_id": soul.id, "output": result.output})

            # Step 5: Append round to transcript
            transcript.append({"round": round_num, "contributions": round_contributions})

        # Step 6: Extract consensus (last agent's output in last round)
        # Note: "consensus" refers to the last agent's output, not necessarily true consensus
        final_output = transcript[-1]["contributions"][-1]["output"]

        # Step 7: Return updated state
        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: json.dumps(transcript, indent=2)},
                "shared_memory": {
                    **state.shared_memory,
                    f"{self.block_id}_consensus": final_output,
                },
                "messages": state.messages
                + [
                    {
                        "role": "system",
                        "content": f"[Block {self.block_id}] MessageBus completed: {len(self.souls)} agents × {self.iterations} rounds",
                    }
                ],
            }
        )


class RouterBlock(BaseBlock):
    """
    Evaluate routing condition using Soul (LLM) or Callable (function).

    Supports two evaluation modes:
    1. Soul evaluator: LLM decides based on current_task
    2. Callable evaluator: Function evaluates state programmatically

    Typical Use: Decision points in workflows (approve/reject, route selection).
    Output: Decision string stored in results and metadata.
    """

    def __init__(
        self,
        block_id: str,
        condition_evaluator: Union[Soul, Callable[[WorkflowState], str]],
        runner: Optional[PhalanxTeamRunner] = None,
    ) -> None:
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

        # Validation: runner required for Soul evaluator
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
            - metadata[f"{block_id}_decision"] = decision string
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

            # Execute routing task with Soul
            # Type narrowing: runner is guaranteed non-None when condition_evaluator is Soul (validated in __init__)
            assert self.runner is not None, "Runner must be provided for Soul evaluator"
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
