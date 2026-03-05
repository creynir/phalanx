"""
Tests for advanced block implementations (ReplannerBlock).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Soul, Task
from phalanx_core.runner import ExecutionResult
from phalanx_core.blocks.implementations import ReplannerBlock


@pytest.fixture
def mock_runner():
    """Mock PhalanxTeamRunner with controlled outputs."""
    runner = MagicMock()
    runner.execute_task = AsyncMock()
    return runner


@pytest.fixture
def planner_soul():
    """Sample planner soul for testing."""
    return Soul(
        id="planner",
        role="Workflow Planner",
        system_prompt="You create detailed execution plans.",
    )


@pytest.mark.asyncio
async def test_replanner_generates_new_steps(mock_runner, planner_soul):
    """
    AC1: pytest libs/core/tests/test_advanced_blocks.py::test_replanner_generates_new_steps -v passes
    - Produces text plan in results[block_id]
    - JSON step list in metadata['{block_id}_new_steps']
    """
    # Mock LLM returns well-formatted plan with 3 steps
    well_formatted_plan = """1. requirements_analysis: Gather authentication requirements and security constraints
2. technology_selection: Choose between OAuth, SAML, or JWT-based auth
3. database_schema: Design user and session tables"""

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=well_formatted_plan
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="main", instruction="Build authentication system")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    # Verify text plan in results
    assert result_state.results["replanner1"] == well_formatted_plan

    # Verify JSON step list in metadata
    steps = result_state.metadata["replanner1_new_steps"]
    assert isinstance(steps, list)
    assert len(steps) == 3

    # Verify step structure with correct keys
    assert steps[0] == {
        "step_id": "requirements_analysis",
        "description": "Gather authentication requirements and security constraints",
    }
    assert steps[1] == {
        "step_id": "technology_selection",
        "description": "Choose between OAuth, SAML, or JWT-based auth",
    }
    assert steps[2] == {
        "step_id": "database_schema",
        "description": "Design user and session tables",
    }

    # Verify message appended
    assert len(result_state.messages) == 1
    assert "[Block replanner1]" in result_state.messages[0]["content"]
    assert "generated 3 step(s)" in result_state.messages[0]["content"]


@pytest.mark.asyncio
async def test_replanner_validates_current_task(mock_runner, planner_soul):
    """AC2: ReplannerBlock validates current_task is not None during execute()."""
    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    state = WorkflowState(current_task=None)

    with pytest.raises(ValueError, match="ReplannerBlock replanner1: state.current_task is None"):
        await block.execute(state)


@pytest.mark.asyncio
async def test_replanner_regex_pattern_parsing(mock_runner, planner_soul):
    """AC3: Regex pattern '^\d+\.\s+([^:]+):\s+(.+)$' successfully parses format '1. step_id: description'."""
    # Test explicit regex pattern with various formats
    test_plan = """1. step_one: First step description
2. step_two: Second step description with more detail
3. step_three: Third step"""

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=test_plan
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="test", instruction="Test task")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    steps = result_state.metadata["replanner1_new_steps"]
    assert len(steps) == 3
    assert steps[0]["step_id"] == "step_one"
    assert steps[0]["description"] == "First step description"
    assert steps[1]["step_id"] == "step_two"
    assert steps[1]["description"] == "Second step description with more detail"
    assert steps[2]["step_id"] == "step_three"
    assert steps[2]["description"] == "Third step"


@pytest.mark.asyncio
async def test_replanner_fallback_creates_generic_step(mock_runner, planner_soul):
    """AC4: Fallback creates single generic step if regex finds no matches."""
    # Mock LLM returns unformatted text (doesn't match pattern)
    unformatted_plan = """Here's my plan for this project:
- First we need to do some research
- Then we should design the system
- Finally implement and test"""

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=unformatted_plan
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="test", instruction="Test task")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    # Verify single generic step created
    steps = result_state.metadata["replanner1_new_steps"]
    assert len(steps) == 1
    assert steps[0]["step_id"] == "replanned_execution"
    assert steps[0]["description"] == unformatted_plan  # Full text since < 200 chars


@pytest.mark.asyncio
async def test_replanner_fallback_truncates_at_200_chars(mock_runner, planner_soul):
    """Verify fallback truncates description at 200 chars."""
    # Create unformatted plan longer than 200 chars
    long_unformatted_plan = "A" * 250 + " some more text"

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=long_unformatted_plan
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="test", instruction="Test task")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    steps = result_state.metadata["replanner1_new_steps"]
    assert len(steps) == 1
    assert steps[0]["step_id"] == "replanned_execution"
    # Verify truncation at 200 chars with "..."
    assert steps[0]["description"] == long_unformatted_plan[:200] + "..."
    assert len(steps[0]["description"]) == 203  # 200 + "..."


@pytest.mark.asyncio
async def test_replanner_regex_with_whitespace_variations(mock_runner, planner_soul):
    """Test regex handles various whitespace around step_id and description."""
    # Test with extra spaces
    plan_with_spaces = """1.   step_with_spaces  :   Description with spaces
2. normal_step: Normal description
3.step_no_space:No space after number"""

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=plan_with_spaces
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="test", instruction="Test task")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    steps = result_state.metadata["replanner1_new_steps"]
    # First line matches because ^\d+\. requires space after period
    # Third line doesn't match because no space after period
    assert len(steps) == 2
    # Verify trimming works
    assert steps[0]["step_id"] == "step_with_spaces"
    assert steps[0]["description"] == "Description with spaces"
    assert steps[1]["step_id"] == "normal_step"
    assert steps[1]["description"] == "Normal description"


@pytest.mark.asyncio
async def test_replanner_preserves_existing_results_and_metadata(mock_runner, planner_soul):
    """ReplannerBlock preserves existing results and metadata."""
    plan = "1. step1: Description 1"

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=plan
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="test", instruction="Test task")
    state = WorkflowState(
        current_task=task,
        results={"previous_block": "Previous result"},
        metadata={"existing_key": "existing_value"},
    )

    result_state = await block.execute(state)

    # Verify existing data preserved
    assert result_state.results["previous_block"] == "Previous result"
    assert result_state.metadata["existing_key"] == "existing_value"

    # Verify new data added
    assert result_state.results["replanner1"] == plan
    assert "replanner1_new_steps" in result_state.metadata


@pytest.mark.asyncio
async def test_replanner_reads_previous_errors_from_shared_memory(mock_runner, planner_soul):
    """ReplannerBlock includes previous errors from shared_memory in planning context."""
    plan = "1. retry_step: Try again with fix"

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=plan
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="test", instruction="Build feature")
    state = WorkflowState(
        current_task=task,
        shared_memory={"replanner1_previous_errors": "Error: Connection timeout"},
    )

    await block.execute(state)

    # Verify the task was called with error context
    call_args = mock_runner.execute_task.call_args
    planning_task = call_args[0][0]
    assert "Original Goal: Build feature" in planning_task.instruction
    assert "Previous Errors:" in planning_task.instruction
    assert "Error: Connection timeout" in planning_task.instruction


@pytest.mark.asyncio
async def test_replanner_multiline_descriptions(mock_runner, planner_soul):
    """Test that regex correctly handles single-line format (multiline descriptions should not match)."""
    # Each step must be on single line - multiline descriptions shouldn't match
    plan_single_line = """1. step1: This is a single line description
2. step2: Another single line
3. step3: Final step"""

    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="replanner1_planning", soul_id="planner", output=plan_single_line
    )

    block = ReplannerBlock("replanner1", planner_soul, mock_runner)
    task = Task(id="test", instruction="Test")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    steps = result_state.metadata["replanner1_new_steps"]
    assert len(steps) == 3
