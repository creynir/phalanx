"""
Tests for Blueprint state machine and validation.
"""

import pytest
from phalanx_core.state import WorkflowState
from phalanx_core.blueprint import Blueprint
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


def test_blueprint_validation_errors():
    """AC-9: Blueprint detects validation errors."""
    bp = Blueprint(name="test_bp")

    # Error: No entry block set
    errors = bp.validate()
    assert len(errors) == 1
    assert "No entry block set" in errors[0]

    # Error: Entry block doesn't exist
    bp.set_entry("nonexistent")
    errors = bp.validate()
    assert any("not found" in e for e in errors)

    # Error: Transition to nonexistent block
    bp.add_block(MockBlock("a"))
    bp.add_transition("a", "b")  # b doesn't exist
    bp.set_entry("a")
    errors = bp.validate()
    assert any("unknown block 'b'" in e for e in errors)


def test_blueprint_cycle_detection():
    """AC-11: Blueprint detects cycles."""
    bp = Blueprint(name="cyclic_bp")
    bp.add_block(MockBlock("a"))
    bp.add_block(MockBlock("b"))
    bp.add_block(MockBlock("c"))

    # Create cycle: a -> b -> c -> a
    bp.add_transition("a", "b")
    bp.add_transition("b", "c")
    bp.add_transition("c", "a")
    bp.set_entry("a")

    errors = bp.validate()
    assert len(errors) == 1
    assert "Cycle detected" in errors[0]


@pytest.mark.asyncio
async def test_blueprint_linear_execution():
    """AC-10: Blueprint executes linear flow."""
    bp = Blueprint(name="linear_bp")

    block_a = MockBlock("a", "Output A")
    block_b = MockBlock("b", "Output B")
    block_c = MockBlock("c", "Output C")

    bp.add_block(block_a)
    bp.add_block(block_b)
    bp.add_block(block_c)
    bp.add_transition("a", "b")
    bp.add_transition("b", "c")
    bp.add_transition("c", None)  # Terminal
    bp.set_entry("a")

    # Validate before run
    errors = bp.validate()
    assert not errors

    # Execute
    initial_state = WorkflowState()
    final_state = await bp.run(initial_state)

    # Verify execution order
    assert block_a.executed
    assert block_b.executed
    assert block_c.executed

    # Verify results accumulated
    assert final_state.results == {"a": "Output A", "b": "Output B", "c": "Output C"}

    # Verify messages appended
    assert len(final_state.messages) == 3


@pytest.mark.asyncio
async def test_blueprint_run_validates():
    """Blueprint.run() validates before execution."""
    bp = Blueprint(name="invalid_bp")
    # No blocks, no entry -> invalid

    with pytest.raises(ValueError, match="Cannot run invalid blueprint"):
        await bp.run(WorkflowState())


def test_blueprint_terminal_transition():
    """Terminal blocks use to_block_id=None (tech lead issue #1)."""
    bp = Blueprint(name="terminal_bp")
    bp.add_block(MockBlock("a"))
    bp.add_transition("a", None)  # Mark as terminal

    # Verify no entry in _transitions
    assert "a" not in bp._transitions


def test_blueprint_duplicate_block_id():
    """Blueprint raises ValueError for duplicate block IDs."""
    bp = Blueprint(name="test_bp")
    bp.add_block(MockBlock("a"))

    with pytest.raises(ValueError, match="already exists"):
        bp.add_block(MockBlock("a"))


def test_blueprint_duplicate_transition():
    """Blueprint raises ValueError for duplicate transitions (single-path only)."""
    bp = Blueprint(name="test_bp")
    bp.add_block(MockBlock("a"))
    bp.add_block(MockBlock("b"))
    bp.add_block(MockBlock("c"))

    bp.add_transition("a", "b")

    with pytest.raises(ValueError, match="already has transition"):
        bp.add_transition("a", "c")
