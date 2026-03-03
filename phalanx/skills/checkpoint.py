"""Checkpoint/Resume at step level for skill execution.

Enables skill runs to survive agent crashes by persisting step-level
completion state to the skill_runs SQLite table.

Key operations:
  save_checkpoint  — mark a step as completed with its result
  load_checkpoint  — restore run state including completed/pending steps
  get_resume_point — return the first incomplete step, or None
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from phalanx.db import StateDB
from phalanx.skills.orchestrator import StepSpec, build_dag, next_ready

logger = logging.getLogger(__name__)


@dataclass
class RunCheckpoint:
    """Snapshot of a skill run's checkpoint state."""

    run_id: str
    status: str
    completed_steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    step_artifacts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_db(cls, data: dict) -> RunCheckpoint:
        return cls(
            run_id=data["run_id"],
            status=data["status"],
            completed_steps=data.get("completed_steps", []),
            current_step=data.get("current_step"),
            step_artifacts=data.get("step_artifacts", {}),
        )


class CheckpointManager:
    """Manages step-level checkpoints for skill runs."""

    def __init__(self, db: StateDB) -> None:
        self._db = db

    def save_checkpoint(
        self,
        run_id: str,
        step_name: str,
        result: str | None = None,
    ) -> None:
        """Mark a step as completed and save its artifact.

        Only fully completed steps are checkpointed — partial
        step execution is restarted from scratch on resume.
        """
        self._db.save_checkpoint(run_id, step_name, result)
        logger.info("Checkpoint saved: run=%s step=%s", run_id, step_name)

    def load_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        """Load the checkpoint state for a skill run."""
        data = self._db.load_checkpoint(run_id)
        if data is None:
            return None
        return RunCheckpoint.from_db(data)

    def get_resume_point(
        self,
        run_id: str,
        all_steps: list[dict] | None = None,
    ) -> StepSpec | None:
        """Return the first incomplete step for a skill run.

        If all_steps is provided, builds a DAG and returns the first
        ready-but-uncompleted step. Otherwise returns based on the
        checkpoint's current_step or first missing step.
        """
        checkpoint = self.load_checkpoint(run_id)
        if checkpoint is None:
            return None

        completed = set(checkpoint.completed_steps)

        if all_steps:
            dag = build_dag(all_steps)
            ready = next_ready(dag, completed)
            return ready[0] if ready else None

        if checkpoint.current_step and checkpoint.current_step not in completed:
            return StepSpec(name=checkpoint.current_step)

        return None

    def set_current_step(self, run_id: str, step_name: str) -> None:
        """Record which step is currently executing (for crash recovery)."""
        self._db.update_skill_run(run_id, current_step=step_name)

    def mark_run_complete(self, run_id: str) -> None:
        """Mark the entire skill run as completed."""
        self._db.update_skill_run(run_id, status="completed", current_step=None)

    def mark_run_failed(self, run_id: str) -> None:
        """Mark the skill run as failed."""
        self._db.update_skill_run(run_id, status="failed")
