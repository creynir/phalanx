"""
Tests for Workflow state machine and validation.
"""

import pytest
from phalanx_core.state import WorkflowState
from phalanx_core.workflow import Workflow
from phalanx_core.blocks.base import BaseBlock


class MockBlock(BaseBlock):
    """Test double for BaseBlock."""

    def __init__(self, block_id: str, output: str = "mock output"):
        super().__init__(block_id)
        self.output = output
        self.executed = False

    async def execute(self, state: WorkflowState) -> WorkflowState:
        self.executed = True
        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: self.output},
                "messages": state.messages
                + [{"role": "system", "content": f"[Block {self.block_id}] Executed"}],
            }
        )


def test_workflow_validation_errors():
    """AC-9: Workflow detects validation errors."""
    wf = Workflow(name="test_wf")

    # Error: No entry block set
    errors = wf.validate()
    assert len(errors) == 1
    assert "No entry block set" in errors[0]

    # Error: Entry block doesn't exist
    wf.set_entry("nonexistent")
    errors = wf.validate()
    assert any("not found" in e for e in errors)

    # Error: Transition to nonexistent block
    wf.add_block(MockBlock("a"))
    wf.add_transition("a", "b")  # b doesn't exist
    wf.set_entry("a")
    errors = wf.validate()
    assert any("unknown block 'b'" in e for e in errors)


def test_workflow_cycle_detection():
    """AC-11: Workflow detects cycles."""
    wf = Workflow(name="cyclic_wf")
    wf.add_block(MockBlock("a"))
    wf.add_block(MockBlock("b"))
    wf.add_block(MockBlock("c"))

    # Create cycle: a -> b -> c -> a
    wf.add_transition("a", "b")
    wf.add_transition("b", "c")
    wf.add_transition("c", "a")
    wf.set_entry("a")

    errors = wf.validate()
    assert len(errors) == 1
    assert "Cycle detected" in errors[0]


@pytest.mark.asyncio
async def test_workflow_linear_execution():
    """AC-10: Workflow executes linear flow."""
    wf = Workflow(name="linear_wf")

    block_a = MockBlock("a", "Output A")
    block_b = MockBlock("b", "Output B")
    block_c = MockBlock("c", "Output C")

    wf.add_block(block_a)
    wf.add_block(block_b)
    wf.add_block(block_c)
    wf.add_transition("a", "b")
    wf.add_transition("b", "c")
    wf.add_transition("c", None)  # Terminal
    wf.set_entry("a")

    # Validate before run
    errors = wf.validate()
    assert not errors

    # Execute
    initial_state = WorkflowState()
    final_state = await wf.run(initial_state)

    # Verify execution order
    assert block_a.executed
    assert block_b.executed
    assert block_c.executed

    # Verify results accumulated
    assert final_state.results == {"a": "Output A", "b": "Output B", "c": "Output C"}

    # Verify messages appended
    assert len(final_state.messages) == 3


@pytest.mark.asyncio
async def test_workflow_run_validates():
    """Workflow.run() validates before execution."""
    wf = Workflow(name="invalid_wf")
    # No blocks, no entry -> invalid

    with pytest.raises(ValueError, match="Cannot run invalid workflow"):
        await wf.run(WorkflowState())


def test_workflow_terminal_transition():
    """Terminal blocks use to_block_id=None (tech lead issue #1)."""
    wf = Workflow(name="terminal_wf")
    wf.add_block(MockBlock("a"))
    wf.add_transition("a", None)  # Mark as terminal

    # Verify no entry in _transitions
    assert "a" not in wf._transitions


def test_workflow_duplicate_block_id():
    """Workflow raises ValueError for duplicate block IDs."""
    wf = Workflow(name="test_wf")
    wf.add_block(MockBlock("a"))

    with pytest.raises(ValueError, match="already exists"):
        wf.add_block(MockBlock("a"))


def test_workflow_duplicate_transition():
    """Workflow raises ValueError for duplicate transitions (single-path only)."""
    wf = Workflow(name="test_wf")
    wf.add_block(MockBlock("a"))
    wf.add_block(MockBlock("b"))
    wf.add_block(MockBlock("c"))

    wf.add_transition("a", "b")

    with pytest.raises(ValueError, match="already has transition"):
        wf.add_transition("a", "c")
