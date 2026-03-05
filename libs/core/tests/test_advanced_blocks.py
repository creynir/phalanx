"""
Tests for advanced block implementations (RouterBlock, AdvisorBlock).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Soul, Task
from phalanx_core.runner import ExecutionResult
from phalanx_core.blocks.implementations import RouterBlock, AdvisorBlock


@pytest.fixture
def mock_runner():
    """Mock PhalanxTeamRunner with controlled outputs."""
    runner = MagicMock()
    runner.execute_task = AsyncMock()
    return runner


@pytest.fixture
def sample_soul():
    """Sample soul for testing."""
    return Soul(id="test_soul", role="Tester", system_prompt="You test things.")


# ==================== RouterBlock Tests ====================


@pytest.mark.asyncio
async def test_router_block_soul_evaluator(mock_runner, sample_soul):
    """RouterBlock with Soul evaluator executes task and stores decision."""
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="approved"
    )

    block = RouterBlock("router1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Should we proceed?")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    assert result_state.results["router1"] == "approved"
    assert result_state.metadata["router1_decision"] == "approved"
    assert len(result_state.messages) == 1
    assert "RouterBlock decision: approved" in result_state.messages[0]["content"]
    mock_runner.execute_task.assert_called_once_with(task, sample_soul)


@pytest.mark.asyncio
async def test_router_block_callable_evaluator():
    """RouterBlock with Callable evaluator uses function to decide."""

    def decision_func(state: WorkflowState) -> str:
        # Simple logic: check if "urgent" in results
        return "fast_track" if state.results.get("priority") == "urgent" else "standard"

    block = RouterBlock("router1", decision_func)
    state = WorkflowState(results={"priority": "urgent"})

    result_state = await block.execute(state)

    assert result_state.results["router1"] == "fast_track"
    assert result_state.metadata["router1_decision"] == "fast_track"


@pytest.mark.asyncio
async def test_router_block_soul_without_runner(sample_soul):
    """RouterBlock raises ValueError if Soul evaluator provided without runner."""
    with pytest.raises(ValueError, match="runner is required when condition_evaluator is Soul"):
        RouterBlock("router1", sample_soul, runner=None)


@pytest.mark.asyncio
async def test_router_block_soul_none_task(mock_runner, sample_soul):
    """RouterBlock with Soul raises ValueError if current_task is None."""
    block = RouterBlock("router1", sample_soul, mock_runner)
    state = WorkflowState(current_task=None)

    with pytest.raises(ValueError, match="state.current_task is None"):
        await block.execute(state)


# ==================== AdvisorBlock Tests ====================


@pytest.mark.asyncio
async def test_advisor_block_analyzes_failure(mock_runner, sample_soul):
    """
    AC-1: AdvisorBlock reads multiple failure_context_keys, produces recommendation
    in results and shared_memory['{block_id}_recommendation'].
    """
    # Setup: mock runner returns recommendation
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="advisor_analysis",
        soul_id="test_soul",
        output="Root cause: Network timeout. Recommendation: Increase timeout to 30s and add retry logic.",
    )

    # Create advisor block with 2 context keys
    block = AdvisorBlock(
        block_id="advisor1",
        failure_context_keys=["retry_errors", "execution_log"],
        advisor_soul=sample_soul,
        runner=mock_runner,
    )

    # Populate shared_memory with mixed types (list and string)
    state = WorkflowState(
        shared_memory={
            "retry_errors": ["Attempt 1: Connection timeout", "Attempt 2: Connection refused"],
            "execution_log": "Started at 10:00, failed at 10:05",
        }
    )

    result_state = await block.execute(state)

    # Verify recommendation stored in both locations
    expected_recommendation = (
        "Root cause: Network timeout. Recommendation: Increase timeout to 30s and add retry logic."
    )
    assert result_state.results["advisor1"] == expected_recommendation
    assert result_state.shared_memory["advisor1_recommendation"] == expected_recommendation

    # Verify message logged
    assert len(result_state.messages) == 1
    assert "AdvisorBlock analyzed 2 context(s)" in result_state.messages[0]["content"]

    # Verify task instruction includes both contexts
    call_args = mock_runner.execute_task.call_args
    task_arg = call_args[0][0]  # First positional arg is Task
    assert "retry_errors" in task_arg.instruction
    assert "execution_log" in task_arg.instruction
    # Verify list formatting with bullet points
    assert "  - Attempt 1: Connection timeout" in task_arg.instruction
    assert "  - Attempt 2: Connection refused" in task_arg.instruction
    # Verify string value included
    assert "Started at 10:00, failed at 10:05" in task_arg.instruction


@pytest.mark.asyncio
async def test_advisor_block_missing_context_keys(mock_runner, sample_soul):
    """
    AC-2: AdvisorBlock raises ValueError with missing keys listed and available keys shown
    if any key missing.
    """
    block = AdvisorBlock(
        block_id="advisor1",
        failure_context_keys=["retry_errors", "execution_log", "system_metrics"],
        advisor_soul=sample_soul,
        runner=mock_runner,
    )

    # Only provide one of the three required keys
    state = WorkflowState(shared_memory={"retry_errors": ["Error 1"], "other_key": "value"})

    with pytest.raises(ValueError) as exc_info:
        await block.execute(state)

    error_msg = str(exc_info.value)
    # Verify missing keys are listed
    assert "execution_log" in error_msg
    assert "system_metrics" in error_msg
    # Verify available keys are shown
    assert "Available keys:" in error_msg
    assert "retry_errors" in error_msg
    assert "other_key" in error_msg


@pytest.mark.asyncio
async def test_advisor_block_empty_failure_context_keys(mock_runner, sample_soul):
    """
    AC-3: AdvisorBlock validates failure_context_keys is non-empty in constructor.
    """
    with pytest.raises(ValueError, match="failure_context_keys cannot be empty"):
        AdvisorBlock(
            block_id="advisor1",
            failure_context_keys=[],
            advisor_soul=sample_soul,
            runner=mock_runner,
        )


@pytest.mark.asyncio
async def test_advisor_block_handles_list_and_string_values(mock_runner, sample_soul):
    """
    AC-4: AdvisorBlock handles both list and string values from shared_memory,
    formatting lists with bullet points.
    """
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="advisor_analysis", soul_id="test_soul", output="Analysis complete"
    )

    block = AdvisorBlock(
        block_id="advisor1",
        failure_context_keys=["errors_list", "status_string", "another_list"],
        advisor_soul=sample_soul,
        runner=mock_runner,
    )

    state = WorkflowState(
        shared_memory={
            "errors_list": ["Error A", "Error B", "Error C"],
            "status_string": "System crashed",
            "another_list": ["Log 1", "Log 2"],
        }
    )

    result_state = await block.execute(state)

    # Verify execution succeeded
    assert result_state.results["advisor1"] == "Analysis complete"

    # Verify task instruction format
    call_args = mock_runner.execute_task.call_args
    task_arg = call_args[0][0]
    instruction = task_arg.instruction

    # Check list formatting (bullet points)
    assert "  - Error A" in instruction
    assert "  - Error B" in instruction
    assert "  - Error C" in instruction
    assert "  - Log 1" in instruction
    assert "  - Log 2" in instruction

    # Check string formatting (no bullet points)
    assert "System crashed" in instruction
    # Ensure string is not formatted with bullet points
    assert "  - System crashed" not in instruction


@pytest.mark.asyncio
async def test_advisor_block_preserves_existing_shared_memory(mock_runner, sample_soul):
    """AdvisorBlock preserves existing shared_memory entries."""
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="advisor_analysis", soul_id="test_soul", output="Recommendation"
    )

    block = AdvisorBlock(
        block_id="advisor1",
        failure_context_keys=["error_log"],
        advisor_soul=sample_soul,
        runner=mock_runner,
    )

    state = WorkflowState(
        shared_memory={
            "error_log": "Connection failed",
            "existing_key": "existing_value",
        }
    )

    result_state = await block.execute(state)

    # Verify existing shared_memory preserved
    assert result_state.shared_memory["existing_key"] == "existing_value"
    assert result_state.shared_memory["error_log"] == "Connection failed"
    # Verify new recommendation added
    assert result_state.shared_memory["advisor1_recommendation"] == "Recommendation"
