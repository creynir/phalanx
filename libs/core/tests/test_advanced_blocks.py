"""
Tests for advanced block implementations (MessageBusBlock).
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Soul, Task
from phalanx_core.runner import ExecutionResult
from phalanx_core.blocks.implementations import MessageBusBlock


@pytest.fixture
def mock_runner():
    """Mock PhalanxTeamRunner with controlled outputs."""
    runner = MagicMock()
    runner.execute_task = AsyncMock()
    return runner


@pytest.fixture
def sample_souls():
    """Sample souls for MessageBusBlock testing."""
    return [
        Soul(id="agent1", role="Researcher", system_prompt="You research."),
        Soul(id="agent2", role="Engineer", system_prompt="You engineer."),
        Soul(id="agent3", role="Ethicist", system_prompt="You analyze ethics."),
        Soul(id="agent4", role="Critic", system_prompt="You critique."),
    ]


# ==================== MessageBusBlock Tests ====================


@pytest.mark.asyncio
async def test_messagebus_n_agents(mock_runner, sample_souls):
    """AC-1: 4 agents × 3 iterations produces JSON transcript with 3 rounds of 4 contributions each."""
    # Create a counter-based mock that returns unique outputs per call
    call_count = [0]

    def create_result(*args, **kwargs):
        call_count[0] += 1
        task = args[0]
        soul = args[1]
        return ExecutionResult(
            task_id=task.id,
            soul_id=soul.id,
            output=f"Output from {soul.id} - call {call_count[0]}",
        )

    mock_runner.execute_task.side_effect = create_result

    # Create MessageBusBlock with 4 agents and 3 iterations
    block = MessageBusBlock("messagebus1", sample_souls, iterations=3, runner=mock_runner)
    task = Task(id="brainstorm", instruction="Generate ideas for AI safety")
    state = WorkflowState(current_task=task)

    # Execute
    result_state = await block.execute(state)

    # Verify transcript format
    transcript_json = result_state.results["messagebus1"]
    transcript = json.loads(transcript_json)

    # Should have 3 rounds
    assert len(transcript) == 3

    # Each round should have 4 contributions
    for round_idx, round_data in enumerate(transcript):
        assert round_data["round"] == round_idx + 1
        assert len(round_data["contributions"]) == 4

        # Verify each contribution has soul_id and output
        for contrib_idx, contrib in enumerate(round_data["contributions"]):
            assert "soul_id" in contrib
            assert "output" in contrib
            assert contrib["soul_id"] == sample_souls[contrib_idx].id

    # Verify consensus stored in shared_memory (last contribution from last round)
    expected_consensus = transcript[-1]["contributions"][-1]["output"]
    assert result_state.shared_memory["messagebus1_consensus"] == expected_consensus

    # Verify message appended
    assert len(result_state.messages) == 1
    assert "[Block messagebus1]" in result_state.messages[0]["content"]
    assert "4 agents × 3 rounds" in result_state.messages[0]["content"]

    # Verify total calls (4 agents × 3 rounds = 12)
    assert mock_runner.execute_task.call_count == 12


@pytest.mark.asyncio
async def test_messagebus_validation(mock_runner, sample_souls):
    """AC-2: ValueError for empty souls list, iterations < 1, or current_task=None."""
    # Test empty souls list
    with pytest.raises(ValueError, match="souls list cannot be empty"):
        MessageBusBlock("messagebus1", [], iterations=3, runner=mock_runner)

    # Test iterations < 1
    with pytest.raises(ValueError, match="iterations must be >= 1, got 0"):
        MessageBusBlock("messagebus1", sample_souls, iterations=0, runner=mock_runner)

    # Test current_task=None
    block = MessageBusBlock("messagebus1", sample_souls, iterations=3, runner=mock_runner)
    state = WorkflowState(current_task=None)

    with pytest.raises(ValueError, match="state.current_task is None"):
        await block.execute(state)


@pytest.mark.asyncio
async def test_messagebus_context_passing(mock_runner, sample_souls):
    """Verify context passing: each agent sees formatted contributions from earlier agents in same round."""
    # Track all task objects passed to execute_task
    task_contexts = []

    def capture_task(*args, **kwargs):
        task = args[0]
        soul = args[1]
        task_contexts.append({"task": task, "soul_id": soul.id})
        return ExecutionResult(task_id=task.id, soul_id=soul.id, output=f"Output from {soul.id}")

    mock_runner.execute_task.side_effect = capture_task

    # Use 3 agents, 2 iterations
    souls = sample_souls[:3]
    block = MessageBusBlock("messagebus1", souls, iterations=2, runner=mock_runner)
    task = Task(id="discussion", instruction="Discuss the topic")
    state = WorkflowState(current_task=task)

    await block.execute(state)

    # Total calls: 3 agents × 2 rounds = 6
    assert len(task_contexts) == 6

    # Round 1:
    # Agent 1 (index 0): should have no context
    assert task_contexts[0]["task"].context is None

    # Agent 2 (index 1): should see agent 1's contribution
    agent2_round1_context = task_contexts[1]["task"].context
    assert agent2_round1_context is not None
    assert "[agent1]:" in agent2_round1_context
    assert "Output from agent1" in agent2_round1_context

    # Agent 3 (index 2): should see agent 1 and agent 2's contributions
    agent3_round1_context = task_contexts[2]["task"].context
    assert agent3_round1_context is not None
    assert "[agent1]:" in agent3_round1_context
    assert "[agent2]:" in agent3_round1_context
    assert "Output from agent1" in agent3_round1_context
    assert "Output from agent2" in agent3_round1_context

    # Round 2:
    # Agent 1 (index 3): should have no context (fresh round)
    assert task_contexts[3]["task"].context is None

    # Agent 2 (index 4): should see only agent 1's contribution from round 2
    agent2_round2_context = task_contexts[4]["task"].context
    assert agent2_round2_context is not None
    assert "[agent1]:" in agent2_round2_context
    assert "Output from agent1" in agent2_round2_context


@pytest.mark.asyncio
async def test_messagebus_transcript_format(mock_runner, sample_souls):
    """AC-4: Transcript format verification with proper JSON structure."""
    mock_runner.execute_task.return_value = ExecutionResult(
        task_id="t1", soul_id="agent1", output="Sample output"
    )

    # Single iteration with 2 agents to simplify
    souls = sample_souls[:2]
    block = MessageBusBlock("messagebus1", souls, iterations=1, runner=mock_runner)
    task = Task(id="task1", instruction="Test instruction")
    state = WorkflowState(current_task=task)

    result_state = await block.execute(state)

    # Parse transcript
    transcript = json.loads(result_state.results["messagebus1"])

    # Verify structure
    assert isinstance(transcript, list)
    assert len(transcript) == 1

    round_data = transcript[0]
    assert "round" in round_data
    assert "contributions" in round_data
    assert round_data["round"] == 1

    contributions = round_data["contributions"]
    assert isinstance(contributions, list)
    assert len(contributions) == 2

    for contrib in contributions:
        assert "soul_id" in contrib
        assert "output" in contrib
        assert isinstance(contrib["soul_id"], str)
        assert isinstance(contrib["output"], str)
