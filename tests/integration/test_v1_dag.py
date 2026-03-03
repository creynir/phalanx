"""Integration tests for v1.0.0 DAG Scheduling & Orchestrator — IT-088 through IT-098."""

from __future__ import annotations

import pytest

from phalanx.skills.orchestrator import (
    CyclicDependencyError,
    MissingDependencyError,
    build_dag,
    compute_levels,
    mark_complete,
    modify_dag,
    next_ready,
)


pytestmark = pytest.mark.integration


class TestIT088_BuildDAGHappyPath:
    """IT-088: Parse 5 steps with depends_on into a valid StepDAG."""

    def test_build_dag(self):
        steps = [
            {"name": "setup", "depends_on": []},
            {"name": "fetch_data", "depends_on": ["setup"]},
            {"name": "parse", "depends_on": ["setup"]},
            {"name": "transform", "depends_on": ["fetch_data", "parse"]},
            {"name": "output", "depends_on": ["transform"]},
        ]
        dag = build_dag(steps)
        assert len(dag.steps) == 5
        assert "setup" in dag.steps
        assert "output" in dag.steps
        assert dag.steps["transform"].depends_on == ["fetch_data", "parse"]


class TestIT089_CyclicDependencyDetection:
    """IT-089: Provide steps A→B→C→A. Verify CyclicDependencyError raised."""

    def test_cycle_detected(self):
        steps = [
            {"name": "A", "depends_on": ["C"]},
            {"name": "B", "depends_on": ["A"]},
            {"name": "C", "depends_on": ["B"]},
        ]
        with pytest.raises(CyclicDependencyError):
            build_dag(steps)


class TestIT090_MissingDependencyReference:
    """IT-090: Step references non-existent depends_on. Verify validation error."""

    def test_missing_dep(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": ["nonexistent"]},
        ]
        with pytest.raises(MissingDependencyError):
            build_dag(steps)


class TestIT091_ComputeLevels:
    """IT-091: Diamond DAG (A→C, B→C, C→D) verifies levels: [A,B], [C], [D]."""

    def test_levels(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": []},
            {"name": "C", "depends_on": ["A", "B"]},
            {"name": "D", "depends_on": ["C"]},
        ]
        dag = build_dag(steps)
        levels = compute_levels(dag)
        assert len(levels) == 3

        level0_names = sorted(s.name for s in levels[0])
        assert level0_names == ["A", "B"]
        assert [s.name for s in levels[1]] == ["C"]
        assert [s.name for s in levels[2]] == ["D"]


class TestIT092_NextReadyInitial:
    """IT-092: With no completed steps, returns all level-0 steps."""

    def test_initial_ready(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": []},
            {"name": "C", "depends_on": ["A", "B"]},
        ]
        dag = build_dag(steps)
        ready = next_ready(dag)
        names = sorted(s.name for s in ready)
        assert names == ["A", "B"]


class TestIT093_NextReadyAfterCompletion:
    """IT-093: Mark level-0 complete, verify level-1 returned."""

    def test_after_completion(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": []},
            {"name": "C", "depends_on": ["A", "B"]},
        ]
        dag = build_dag(steps)
        mark_complete(dag, "A")
        mark_complete(dag, "B")
        ready = next_ready(dag)
        assert len(ready) == 1
        assert ready[0].name == "C"


class TestIT094_MarkComplete:
    """IT-094: Downstream dependents unlocked only when all dependencies satisfied."""

    def test_mark_complete(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": []},
            {"name": "C", "depends_on": ["A", "B"]},
        ]
        dag = build_dag(steps)
        mark_complete(dag, "A")
        ready = next_ready(dag)
        # C should NOT be ready because B is not complete
        names = [s.name for s in ready]
        assert "C" not in names
        assert "B" in names

        mark_complete(dag, "B")
        ready = next_ready(dag)
        assert ready[0].name == "C"


class TestIT095_SingleStepDAG:
    """IT-095: Single step with no dependencies executes immediately."""

    def test_single_step(self):
        steps = [{"name": "only_step", "depends_on": []}]
        dag = build_dag(steps)
        ready = next_ready(dag)
        assert len(ready) == 1
        assert ready[0].name == "only_step"


class TestIT096_ParallelFlagVsDAG:
    """IT-096: parallel: true controls agent parallelism vs DAG step-level parallelism."""

    def test_parallel_flag(self):
        steps = [
            {"name": "A", "depends_on": [], "parallel": True},
            {"name": "B", "depends_on": [], "parallel": False},
        ]
        dag = build_dag(steps)
        assert dag.steps["A"].parallel is True
        assert dag.steps["B"].parallel is False
        ready = next_ready(dag)
        assert len(ready) == 2


class TestIT097_DAGHotModification:
    """IT-097: After EngineeringManagerStep modifies DAG, next_ready() reflects new topology."""

    def test_hot_modify(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": ["A"]},
        ]
        dag = build_dag(steps)
        mark_complete(dag, "A")

        modify_dag(
            dag,
            [
                {"op": "add", "step": {"name": "C", "depends_on": ["A"]}},
            ],
        )
        ready = next_ready(dag)
        names = sorted(s.name for s in ready)
        assert "B" in names
        assert "C" in names


class TestIT098_DAGModificationCycleRejection:
    """IT-098: Engineering manager insert creating cycle is rejected without corrupting DAG."""

    def test_cycle_rejection(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": ["A"]},
        ]
        dag = build_dag(steps)

        with pytest.raises(CyclicDependencyError):
            modify_dag(
                dag,
                [
                    {"op": "add", "step": {"name": "C", "depends_on": ["B"]}},
                    {"op": "modify", "name": "A", "updates": {"depends_on": ["C"]}},
                ],
            )
