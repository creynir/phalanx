"""
Tests for extended primitives: Step and Skill classes.
"""

import pytest
from unittest.mock import AsyncMock
from phalanx_core.primitives import Skill
from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Task


@pytest.mark.asyncio
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
