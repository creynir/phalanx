"""DAG Scheduling with Topological Sort for step-level execution.

The DAGOrchestrator manages a directed acyclic graph of skill steps,
enabling parallel execution of independent steps and enforcing
dependency ordering.

Key operations:
  build_dag      — parse step specs with depends_on into a StepDAG
  compute_levels — topological sort into parallel execution levels
  next_ready     — return steps whose dependencies are all satisfied
  mark_complete  — record completion, unlock downstream dependents
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class CyclicDependencyError(Exception):
    """Raised when the DAG contains a cycle."""

    pass


class MissingDependencyError(Exception):
    """Raised when a depends_on reference points to a non-existent step."""

    pass


@dataclass
class StepSpec:
    """Specification for a single step in a skill."""

    name: str
    type: str = "worker"  # worker, team_lead, engineering_manager
    depends_on: list[str] = field(default_factory=list)
    parallel: bool = False
    prompt: str = ""
    on_failure: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "depends_on": self.depends_on,
            "parallel": self.parallel,
            "prompt": self.prompt,
            "on_failure": self.on_failure,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StepSpec:
        return cls(
            name=d["name"],
            type=d.get("type", "worker"),
            depends_on=d.get("depends_on", []),
            parallel=d.get("parallel", False),
            prompt=d.get("prompt", ""),
            on_failure=d.get("on_failure", {}),
            config=d.get("config", {}),
        )


@dataclass
class StepDAG:
    """A directed acyclic graph of step execution."""

    steps: dict[str, StepSpec] = field(default_factory=dict)
    adjacency: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    reverse_adj: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    completed: set[str] = field(default_factory=set)
    step_results: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "completed": list(self.completed),
            "step_results": self.step_results,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def build_dag(steps: list[dict | StepSpec]) -> StepDAG:
    """Parse step specifications into a validated DAG.

    Raises CyclicDependencyError if cycles are detected.
    Raises MissingDependencyError if depends_on references are invalid.
    """
    dag = StepDAG()

    for step_data in steps:
        if isinstance(step_data, StepSpec):
            spec = step_data
        else:
            spec = StepSpec.from_dict(step_data)
        dag.steps[spec.name] = spec

    all_names = set(dag.steps.keys())
    for name, spec in dag.steps.items():
        for dep in spec.depends_on:
            if dep not in all_names:
                raise MissingDependencyError(
                    f"Step '{name}' depends on '{dep}' which does not exist"
                )
            dag.adjacency[dep].append(name)
            dag.reverse_adj[name].append(dep)

    _detect_cycles(dag)

    return dag


def _detect_cycles(dag: StepDAG) -> None:
    """DFS-based cycle detection. Raises CyclicDependencyError if found."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in dag.steps}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in dag.adjacency.get(node, []):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                raise CyclicDependencyError(f"Cycle detected: {' -> '.join(cycle)}")
            if color[neighbor] == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for name in dag.steps:
        if color[name] == WHITE:
            dfs(name, [])


def compute_levels(dag: StepDAG) -> list[list[StepSpec]]:
    """Topological sort into execution levels.

    Level 0 contains steps with no dependencies.
    Level N contains steps whose dependencies are all in levels < N.
    """
    in_degree = {name: 0 for name in dag.steps}
    for name in dag.steps:
        for dep in dag.steps[name].depends_on:
            in_degree[name] += 1

    queue = deque(name for name, deg in in_degree.items() if deg == 0)
    levels: list[list[StepSpec]] = []

    while queue:
        level = []
        next_queue = deque()
        for name in queue:
            level.append(dag.steps[name])
            for downstream in dag.adjacency.get(name, []):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    next_queue.append(downstream)
        levels.append(level)
        queue = next_queue

    assigned = sum(len(lv) for lv in levels)
    if assigned != len(dag.steps):
        raise CyclicDependencyError(
            f"Topological sort incomplete: {assigned}/{len(dag.steps)} steps assigned"
        )

    return levels


def next_ready(dag: StepDAG, completed: set[str] | None = None) -> list[StepSpec]:
    """Return all steps whose dependencies are fully satisfied.

    Uses the DAG's internal completed set merged with the provided set.
    """
    done = dag.completed | (completed or set())
    ready = []
    for name, spec in dag.steps.items():
        if name in done:
            continue
        if all(dep in done for dep in spec.depends_on):
            ready.append(spec)
    return ready


def mark_complete(dag: StepDAG, step_name: str, result: str | None = None) -> None:
    """Record step completion, unlocking downstream dependents."""
    dag.completed.add(step_name)
    if result is not None:
        dag.step_results[step_name] = result
    logger.debug(
        "Step '%s' complete. Completed: %d/%d",
        step_name,
        len(dag.completed),
        len(dag.steps),
    )


def modify_dag(
    dag: StepDAG,
    changes: list[dict],
) -> StepDAG:
    """Apply engineering manager modifications to remaining (non-completed) steps.

    Change types:
      {"op": "add", "step": {...}}     — add a new step
      {"op": "remove", "name": "..."}  — remove a step (if not completed)
      {"op": "modify", "name": "...", "updates": {...}} — modify step fields

    Validates the modified DAG for cycles before returning.
    Raises CyclicDependencyError if modifications introduce cycles.
    """
    for change in changes:
        op = change.get("op")

        if op == "add":
            spec = StepSpec.from_dict(change["step"])
            dag.steps[spec.name] = spec
            for dep in spec.depends_on:
                dag.adjacency[dep].append(spec.name)
                dag.reverse_adj[spec.name].append(dep)

        elif op == "remove":
            name = change["name"]
            if name in dag.completed:
                logger.warning("Cannot remove completed step '%s'", name)
                continue
            if name in dag.steps:
                for dep in dag.steps[name].depends_on:
                    if name in dag.adjacency.get(dep, []):
                        dag.adjacency[dep].remove(name)
                for downstream in list(dag.adjacency.get(name, [])):
                    if name in dag.reverse_adj.get(downstream, []):
                        dag.reverse_adj[downstream].remove(name)
                        dag.steps[downstream].depends_on.remove(name)
                del dag.adjacency[name]
                del dag.steps[name]

        elif op == "modify":
            name = change["name"]
            if name in dag.completed:
                logger.warning("Cannot modify completed step '%s'", name)
                continue
            if name in dag.steps:
                updates = change.get("updates", {})
                spec = dag.steps[name]

                if "depends_on" in updates:
                    old_deps = list(spec.depends_on)
                    for dep in old_deps:
                        if name in dag.adjacency.get(dep, []):
                            dag.adjacency[dep].remove(name)
                    dag.reverse_adj[name] = []

                for key, value in updates.items():
                    if hasattr(spec, key):
                        setattr(spec, key, value)

                if "depends_on" in updates:
                    for dep in spec.depends_on:
                        dag.adjacency[dep].append(name)
                        dag.reverse_adj[name].append(dep)

    _detect_cycles(dag)
    return dag
