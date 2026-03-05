"""
Workflow state machine for orchestrating block execution.
"""

from typing import Dict, List, Optional
from phalanx_core.state import WorkflowState
from phalanx_core.blocks.base import BaseBlock


class Workflow:
    """
    Orchestrates block execution following a transition graph.

    Execution Model: Sequential (one block at a time), single-path transitions.
    Validation: Topology checks (entry exists, no dangling refs, acyclic).

    Example:
        wf = Workflow(name="research_pipeline")
        wf.add_block(research_block)
        wf.add_block(code_block)
        wf.add_transition("research", "code")  # research -> code
        wf.set_entry("research")
        errors = wf.validate()
        if errors:
            raise ValueError(f"Invalid workflow: {errors}")
        final_state = await wf.run(initial_state)
    """

    def __init__(self, name: str):
        """
        Args:
            name: Workflow identifier (for logging/debugging).

        Raises:
            ValueError: If name is empty.
        """
        if not name:
            raise ValueError("Workflow name cannot be empty")
        self.name = name
        self._blocks: Dict[str, BaseBlock] = {}
        self._transitions: Dict[str, str] = {}  # from_block_id -> to_block_id
        self._entry_block_id: Optional[str] = None

    def add_block(self, block: BaseBlock) -> "Workflow":
        """
        Register a block in this workflow.

        Args:
            block: Block instance to add.

        Returns:
            Self (for fluent API chaining).

        Raises:
            ValueError: If block.block_id already registered.
        """
        if block.block_id in self._blocks:
            raise ValueError(
                f"Block ID '{block.block_id}' already exists in blueprint '{self.name}'"
            )
        self._blocks[block.block_id] = block
        return self

    def add_transition(self, from_block_id: str, to_block_id: Optional[str]) -> "Workflow":
        """
        Define transition from one block to another.

        TERMINAL SEMANTICS: Use to_block_id=None to mark a block as terminal (no outgoing transition).

        Args:
            from_block_id: Source block ID.
            to_block_id: Destination block ID, or None for terminal blocks.

        Returns:
            Self (for fluent API chaining).

        Raises:
            ValueError: If from_block_id already has a transition defined.

        Note: Validation of block existence is deferred to validate() method.
              This allows building workflows in any order (add blocks after transitions).
        """
        if from_block_id in self._transitions:
            raise ValueError(
                f"Block '{from_block_id}' already has transition to '{self._transitions[from_block_id]}'. "
                "Only single-path transitions are supported."
            )
        if to_block_id is not None:
            self._transitions[from_block_id] = to_block_id
        # If to_block_id is None, do NOT add entry to _transitions (terminal block)
        return self

    def set_entry(self, block_id: str) -> "Workflow":
        """
        Set the starting block for execution.

        Args:
            block_id: ID of entry block.

        Returns:
            Self (for fluent API chaining).

        Note: Validation of block existence is deferred to validate().
        """
        self._entry_block_id = block_id
        return self

    def validate(self) -> List[str]:
        """
        Validate workflow topology. Returns list of error messages (empty if valid).

        Checks:
        1. Entry block is set and exists in _blocks
        2. All transition references point to registered blocks
        3. No cycles (DFS-based cycle detection)

        Returns:
            List of error strings. Empty list means workflow is valid.

        Example:
            errors = workflow.validate()
            if errors:
                raise ValueError(f"Workflow invalid: {errors}")
        """
        errors: List[str] = []

        # Check 1: Entry block exists
        if self._entry_block_id is None:
            errors.append("No entry block set. Call set_entry(block_id) before validation.")
        elif self._entry_block_id not in self._blocks:
            errors.append(
                f"Entry block '{self._entry_block_id}' not found. "
                f"Available blocks: {list(self._blocks.keys())}"
            )

        # Check 2: All transitions reference valid blocks
        for from_id, to_id in self._transitions.items():
            if from_id not in self._blocks:
                errors.append(f"Transition from unknown block '{from_id}' to '{to_id}'")
            if to_id not in self._blocks:
                errors.append(f"Transition from '{from_id}' to unknown block '{to_id}'")

        # Check 3: Cycle detection (DFS)
        if not errors:  # Only check cycles if structure is valid
            cycle = self._detect_cycle()
            if cycle:
                errors.append(f"Cycle detected: {' -> '.join(cycle)}")

        return errors

    def _detect_cycle(self) -> Optional[List[str]]:
        """
        DFS-based cycle detection. Returns cycle path if found, None otherwise.

        Algorithm: Track visiting (grey) and visited (black) nodes. If we encounter
        a grey node, we have a cycle.
        """
        WHITE, GREY, BLACK = 0, 1, 2
        color: Dict[str, int] = {bid: WHITE for bid in self._blocks}
        parent: Dict[str, Optional[str]] = {bid: None for bid in self._blocks}

        def dfs(node: str) -> Optional[List[str]]:
            color[node] = GREY

            if node in self._transitions:
                neighbor = self._transitions[node]
                if color[neighbor] == GREY:
                    # Cycle detected, reconstruct path
                    cycle_path = [neighbor]
                    current = node
                    while current != neighbor:
                        cycle_path.append(current)
                        parent_node = parent[current]
                        assert parent_node is not None, "Parent must exist in cycle path"
                        current = parent_node
                    cycle_path.append(neighbor)
                    return list(reversed(cycle_path))
                elif color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = dfs(neighbor)
                    if result:
                        return result

            color[node] = BLACK
            return None

        # Start DFS from entry block
        if self._entry_block_id and self._entry_block_id in self._blocks:
            result = dfs(self._entry_block_id)
            if result:
                return result

        # Check unreachable components (could have cycles not reachable from entry)
        for block_id in self._blocks:
            if color[block_id] == WHITE:
                result = dfs(block_id)
                if result:
                    return result

        return None

    async def run(self, initial_state: WorkflowState) -> WorkflowState:
        """
        Execute workflow starting from entry block, following transitions until terminal.

        Args:
            initial_state: Starting workflow state.

        Returns:
            Final workflow state after all blocks execute.

        Raises:
            ValueError: If workflow fails validation.
            Exception: If any block execution fails (propagates from block.execute()).
        """
        # Validate before execution
        errors = self.validate()
        if errors:
            raise ValueError(f"Cannot run invalid workflow '{self.name}': {errors}")

        current_block_id = self._entry_block_id
        state = initial_state

        while current_block_id is not None:
            # Execute current block
            block = self._blocks[current_block_id]
            state = await block.execute(state)

            # Follow transition to next block (None if terminal)
            current_block_id = self._transitions.get(current_block_id)

        return state
