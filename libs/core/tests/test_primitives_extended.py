"""
Tests for extended primitives: Step.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Soul, Task, Step, Skill
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
async def test_step_executes_hooks(mock_runner, sample_soul):
    """
    AC-1: pytest libs/core/tests/test_primitives_extended.py::test_step_executes_hooks -v passes
    - pre_hook runs, then block, then post_hook
    - state flows through all three phases
    """
    # Setup mock runner to return a result
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="Block output"
    )

    # Create a LinearBlock as the wrapped block
    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    initial_state = WorkflowState(current_task=task)

    # Define hooks that track execution order by mutating state.metadata
    def pre_hook(state: WorkflowState) -> WorkflowState:
        return state.model_copy(
            update={
                "metadata": {
                    **state.metadata,
                    "pre_hook_ran": True,
                    "execution_order": ["pre_hook"],
                }
            }
        )

    def post_hook(state: WorkflowState) -> WorkflowState:
        execution_order = state.metadata.get("execution_order", [])
        execution_order.append("post_hook")
        return state.model_copy(
            update={
                "metadata": {
                    **state.metadata,
                    "post_hook_ran": True,
                    "execution_order": execution_order,
                }
            }
        )

    # Create Step with both hooks
    step = Step(block, pre_hook=pre_hook, post_hook=post_hook)

    # Execute
    result_state = await step.execute(initial_state)

    # Verify execution order: pre_hook → block → post_hook
    assert result_state.metadata["pre_hook_ran"] is True
    assert result_state.metadata["post_hook_ran"] is True
    assert result_state.metadata["execution_order"] == ["pre_hook", "post_hook"]

    # Verify block executed successfully
    assert result_state.results["linear1"] == "Block output"
    assert len(result_state.messages) == 1
    assert "[Block linear1]" in result_state.messages[0]["content"]


@pytest.mark.asyncio
async def test_step_no_hooks(mock_runner, sample_soul):
    """
    AC-4: Hooks can be None, in which case that phase is skipped.
    Test with both hooks as None - verify block executes normally.
    """
    # Setup mock runner
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="Block output"
    )

    # Create block and state
    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    initial_state = WorkflowState(current_task=task)

    # Create Step with no hooks
    step = Step(block, pre_hook=None, post_hook=None)

    # Execute
    result_state = await step.execute(initial_state)

    # Verify block executed normally
    assert result_state.results["linear1"] == "Block output"
    assert len(result_state.messages) == 1
    assert "[Block linear1]" in result_state.messages[0]["content"]


@pytest.mark.asyncio
async def test_step_only_pre_hook(mock_runner, sample_soul):
    """
    AC-4: Test with only pre_hook present, post_hook=None.
    """
    # Setup mock runner
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="Block output"
    )

    # Create block and state
    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    initial_state = WorkflowState(current_task=task)

    # Define only pre_hook
    def pre_hook(state: WorkflowState) -> WorkflowState:
        return state.model_copy(update={"metadata": {**state.metadata, "pre_hook_ran": True}})

    # Create Step with only pre_hook
    step = Step(block, pre_hook=pre_hook, post_hook=None)

    # Execute
    result_state = await step.execute(initial_state)

    # Verify pre_hook ran
    assert result_state.metadata["pre_hook_ran"] is True

    # Verify block executed
    assert result_state.results["linear1"] == "Block output"


@pytest.mark.asyncio
async def test_step_only_post_hook(mock_runner, sample_soul):
    """
    AC-4: Test with only post_hook present, pre_hook=None.
    """
    # Setup mock runner
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="Block output"
    )

    # Create block and state
    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    initial_state = WorkflowState(current_task=task)

    # Define only post_hook
    def post_hook(state: WorkflowState) -> WorkflowState:
        return state.model_copy(update={"metadata": {**state.metadata, "post_hook_ran": True}})

    # Create Step with only post_hook
    step = Step(block, pre_hook=None, post_hook=post_hook)

    # Execute
    result_state = await step.execute(initial_state)

    # Verify post_hook ran
    assert result_state.metadata["post_hook_ran"] is True

    # Verify block executed
    assert result_state.results["linear1"] == "Block output"


@pytest.mark.asyncio
async def test_step_state_flows_through_phases(mock_runner, sample_soul):
    """
    Verify that state flows correctly through all three phases:
    - pre_hook modifies state
    - block sees modified state and updates it
    - post_hook sees block's output and can further modify
    """
    # Setup mock runner
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="test_soul", output="Block output"
    )

    # Create block and state
    block = LinearBlock("linear1", sample_soul, mock_runner)
    task = Task(id="t1", instruction="Test task")
    initial_state = WorkflowState(current_task=task)

    # Define hooks that add to shared_memory to track state flow
    def pre_hook(state: WorkflowState) -> WorkflowState:
        return state.model_copy(
            update={"shared_memory": {**state.shared_memory, "pre_value": "from_pre"}}
        )

    def post_hook(state: WorkflowState) -> WorkflowState:
        # Post hook can see both pre_hook's addition and block's result
        assert state.shared_memory["pre_value"] == "from_pre"
        assert state.results["linear1"] == "Block output"
        return state.model_copy(
            update={"shared_memory": {**state.shared_memory, "post_value": "from_post"}}
        )

    # Create Step
    step = Step(block, pre_hook=pre_hook, post_hook=post_hook)

    # Execute
    result_state = await step.execute(initial_state)

    # Verify all state modifications are present in final state
    assert result_state.shared_memory["pre_value"] == "from_pre"
    assert result_state.shared_memory["post_value"] == "from_post"
    assert result_state.results["linear1"] == "Block output"


async def test_skill_runs_blueprint() -> None:
    """
    Test that Skill wraps Blueprint, run() delegates to blueprint.run(), and returns final state.
    """
    # Create mock blueprint
    mock_blueprint = AsyncMock()

    # Initial state with some data
    initial_state = WorkflowState(
        current_task=Task(id="task1", instruction="Test task"),
        results={"previous_block": "previous result"},
    )

    # Expected final state from blueprint (with some additional results)
    final_state_from_blueprint = WorkflowState(
        current_task=Task(id="task1", instruction="Test task"),
        results={"previous_block": "previous result", "blueprint_block": "blueprint output"},
        metadata={
            "active_skill_id": "test_skill",
            "active_skill_description": "Test skill description",
        },
    )

    # Mock blueprint.run() to return final state
    mock_blueprint.run.return_value = final_state_from_blueprint

    # Create Skill
    skill = Skill(
        skill_id="test_skill", description="Test skill description", blueprint=mock_blueprint
    )

    # Run skill
    result_state = await skill.run(initial_state)

    # Verify blueprint.run() was called with state containing active_skill_id
    mock_blueprint.run.assert_called_once()
    called_state = mock_blueprint.run.call_args[0][0]
    assert called_state.metadata["active_skill_id"] == "test_skill"
    assert called_state.metadata["active_skill_description"] == "Test skill description"

    # Verify final state has results from blueprint
    assert result_state.results["blueprint_block"] == "blueprint output"

    # Verify active_skill_* keys are removed from final metadata
    assert "active_skill_id" not in result_state.metadata
    assert "active_skill_description" not in result_state.metadata


@pytest.mark.asyncio
async def test_skill_validates_skill_id_empty() -> None:
    """
    Test that Skill validates skill_id is non-empty and raises ValueError.
    """
    mock_blueprint = AsyncMock()

    with pytest.raises(ValueError, match="Skill skill_id cannot be empty"):
        Skill(skill_id="", description="Valid description", blueprint=mock_blueprint)


@pytest.mark.asyncio
async def test_skill_validates_description_empty() -> None:
    """
    Test that Skill validates description is non-empty and raises ValueError.
    """
    mock_blueprint = AsyncMock()

    with pytest.raises(ValueError, match="Skill description cannot be empty"):
        Skill(skill_id="valid_id", description="", blueprint=mock_blueprint)


@pytest.mark.asyncio
async def test_skill_metadata_lifecycle() -> None:
    """
    Test that skill metadata is present during execution and absent in final state.
    """
    # Create mock blueprint
    mock_blueprint = AsyncMock()

    # Track the state passed to blueprint.run()
    captured_state = None

    async def mock_run(state: WorkflowState) -> WorkflowState:
        nonlocal captured_state
        captured_state = state
        # Return state with some changes but keep metadata
        return state.model_copy(
            update={"results": {**state.results, "blueprint_result": "success"}}
        )

    mock_blueprint.run = mock_run

    # Create initial state without skill metadata
    initial_state = WorkflowState(
        current_task=Task(id="task1", instruction="Test task"),
        metadata={"existing_key": "existing_value"},
    )

    # Create Skill
    skill = Skill(
        skill_id="lifecycle_skill", description="Testing lifecycle", blueprint=mock_blueprint
    )

    # Run skill
    result_state = await skill.run(initial_state)

    # Verify metadata was present during blueprint execution
    assert captured_state is not None
    assert captured_state.metadata["active_skill_id"] == "lifecycle_skill"
    assert captured_state.metadata["active_skill_description"] == "Testing lifecycle"
    assert captured_state.metadata["existing_key"] == "existing_value"

    # Verify metadata is cleaned in final state
    assert "active_skill_id" not in result_state.metadata
    assert "active_skill_description" not in result_state.metadata
    # Verify existing metadata is preserved
    assert result_state.metadata["existing_key"] == "existing_value"
    # Verify blueprint results are present
    assert result_state.results["blueprint_result"] == "success"
