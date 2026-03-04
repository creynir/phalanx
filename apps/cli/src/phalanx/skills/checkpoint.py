"""Step-level checkpoint management for skill runs.

Persists completed steps so that interrupted skill runs can resume
from the last successful step rather than restarting from scratch.
In Phase 1.1 this works without DAG StepSpec objects — step specs
are plain dicts with 'name' and 'depends_on' keys.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phalanx.db import StateDB

logger = logging.getLogger(__name__)


@dataclass
class RunCheckpoint:
    """Snapshot of a skill run's checkpoint state."""

    run_id: str
    status: str = "running"
    completed_steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    step_artifacts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_db(cls, data: dict) -> "RunCheckpoint":
        return cls(
            run_id=data["run_id"],
            status=data.get("status", "running"),
            completed_steps=data.get("completed_steps", []),
            current_step=data.get("current_step"),
            step_artifacts=data.get("step_artifacts", {}),
        )


@dataclass
class _StepSpec:
    """Minimal step spec for resume point resolution."""

    name: str
    depends_on: list[str] = field(default_factory=list)


class CheckpointManager:
    """Manages step-level checkpoints for skill runs."""

    def __init__(self, db: "StateDB") -> None:
        self._db = db

    def save_checkpoint(
        self,
        run_id: str,
        step_name: str,
        result: str | None = None,
    ) -> None:
        """Mark a step as completed and optionally record its artifact."""
        self._db.save_checkpoint(run_id, step_name, step_result=result)
        logger.debug("Checkpoint saved: run=%s step=%s", run_id, step_name)

    def load_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        """Load checkpoint state for a skill run."""
        data = self._db.load_checkpoint(run_id)
        if data is None:
            return None
        return RunCheckpoint.from_db(data)

    def get_resume_point(
        self,
        run_id: str,
        all_steps: list[dict] | None = None,
    ) -> _StepSpec | None:
        """Return the first incomplete step, in dependency order.

        Returns None if all steps are complete or no steps are given.
        """
        cp = self.load_checkpoint(run_id)
        if cp is None or not all_steps:
            return None

        completed = set(cp.completed_steps)

        # Topological ordering: respect depends_on
        for step_dict in all_steps:
            name = step_dict.get("name", "")
            if name not in completed:
                return _StepSpec(
                    name=name,
                    depends_on=step_dict.get("depends_on", []),
                )
        return None

    def set_current_step(self, run_id: str, step_name: str) -> None:
        """Record the step currently in progress (not yet completed)."""
        self._db.update_skill_run(run_id, current_step=step_name)

    def mark_run_complete(self, run_id: str) -> None:
        """Mark the skill run as completed."""
        self._db.update_skill_run(run_id, status="completed", current_step=None)

    def mark_run_failed(self, run_id: str, reason: str | None = None) -> None:
        """Mark the skill run as failed."""
        self._db.update_skill_run(run_id, status="failed", current_step=None)
        if reason:
            logger.warning("Skill run %s failed: %s", run_id, reason)
