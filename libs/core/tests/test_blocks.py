"""
Tests for block implementations.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Soul, Task
from phalanx_core.runner import ExecutionResult
from phalanx_core.blocks.implementations import LinearBlock


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


@pytest.mark.asyncio
async def test_linear_block_execution(mock_runner, sample_soul):
    """AC-5: LinearBlock executes task and stores result."""
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="Test output"
    )

    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    assert result_state.results["linear1"] == "Test output"
    assert len(result_state.messages) == 1
    assert "[Block linear1]" in result_state.messages[0]["content"]
    assert "Completed: Test output" in result_state.messages[0]["content"]
    mock_runner.execute_task.assert_called_once_with(task, sample_soul)


@pytest.mark.asyncio
async def test_linear_block_none_task(mock_runner, sample_soul):
    """LinearBlock raises ValueError if current_task is None."""
    block = LinearBlock("linear1", sample_soul, mock_runner)
    state = WorkflowState(current_task=None)

    with pytest.raises(ValueError, match="current_task is None"):
        await block.execute(state)


@pytest.mark.asyncio
async def test_linear_block_message_truncation(mock_runner, sample_soul):
    """LinearBlock truncates long outputs in message log."""
    # Create a very long output (300 chars)
    long_output = "A" * 300

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output=long_output
    )

    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    # Full output stored in results
    assert result_state.results["linear1"] == long_output
    assert len(result_state.results["linear1"]) == 300

    # But message content is truncated to 200 chars + "..."
    message_content = result_state.messages[0]["content"]
    assert "..." in message_content
    # The truncated part should be 200 chars of "A" plus the "..." suffix
    assert "A" * 200 + "..." in message_content


@pytest.mark.asyncio
async def test_linear_block_preserves_existing_results(mock_runner, sample_soul):
    """LinearBlock preserves existing results when adding new ones."""
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="New output"
    )

    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    state = WorkflowState(current_task=task, results={"previous_block": "Previous output"})

    result_state = await block.execute(state)

    # Both old and new results should be present
    assert result_state.results["previous_block"] == "Previous output"
    assert result_state.results["linear1"] == "New output"


@pytest.mark.asyncio
async def test_linear_block_preserves_existing_messages(mock_runner, sample_soul):
    """LinearBlock appends to existing messages."""
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="Output"
    )

    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    existing_messages = [{"role": "system", "content": "Previous message"}]
    state = WorkflowState(current_task=task, messages=existing_messages)

    result_state = await block.execute(state)

    # Should have 2 messages: existing + new
    assert len(result_state.messages) == 2
    assert result_state.messages[0]["content"] == "Previous message"
    assert "[Block linear1]" in result_state.messages[1]["content"]
