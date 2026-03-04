"""Failure escalation routing for the 3-loop adaptive control system.

In Phase 1.1 this works without DAG StepSpecs. Failures are routed based on
plain worker task completion state rather than structured DAG steps.

Escalation chain:
  retry → invoke_team_lead → invoke_engineering_manager → human_escalation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class EscalationLevel(str, Enum):
    RETRY = "retry"
    INVOKE_TEAM_LEAD = "invoke_team_lead"
    INVOKE_ENGINEERING_MANAGER = "invoke_engineering_manager"
    HUMAN_ESCALATION = "human_escalation"


@dataclass
class EscalationDecision:
    """Result of the escalation routing logic."""

    level: EscalationLevel
    retry_count: int = 0
    max_retries: int = 3
    feedback: str | None = None
    team_lead_exhausted: bool = False
    engineering_manager_exhausted: bool = False

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "feedback": self.feedback,
            "team_lead_exhausted": self.team_lead_exhausted,
            "engineering_manager_exhausted": self.engineering_manager_exhausted,
        }


@dataclass
class FailureContext:
    """Accumulated context about a worker failure across retries."""

    step_name: str
    failure_outputs: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    feedback_injection: bool = True
    team_lead_invoked: bool = False
    team_lead_strategy: str | None = None
    engineering_manager_invoked: bool = False

    def add_failure(self, output: str) -> None:
        self.failure_outputs.append(output)
        self.retry_count += 1


class FailureEscalator:
    """Routes worker failures through the 3-loop escalation chain.

    In Phase 1.1: no DAG dependency — works with plain worker task failures.
    """

    def __init__(self) -> None:
        self._contexts: dict[str, FailureContext] = {}

    def get_or_create_context(
        self,
        step_name: str,
        max_retries: int = 3,
        feedback_injection: bool = True,
    ) -> FailureContext:
        if step_name not in self._contexts:
            self._contexts[step_name] = FailureContext(
                step_name=step_name,
                max_retries=max_retries,
                feedback_injection=feedback_injection,
            )
        return self._contexts[step_name]

    def record_failure(self, step_name: str, output: str) -> FailureContext:
        """Record a failure and return the updated context."""
        ctx = self.get_or_create_context(step_name)
        ctx.add_failure(output)
        return ctx

    def decide(self, step_name: str) -> EscalationDecision:
        """Determine the next escalation action for a failed step."""
        ctx = self._contexts.get(step_name)
        if ctx is None:
            return EscalationDecision(level=EscalationLevel.RETRY)

        if ctx.retry_count <= ctx.max_retries and not ctx.team_lead_invoked:
            if ctx.retry_count < ctx.max_retries:
                return EscalationDecision(
                    level=EscalationLevel.RETRY,
                    retry_count=ctx.retry_count,
                    max_retries=ctx.max_retries,
                    feedback=self._build_feedback(ctx),
                )
            else:
                return EscalationDecision(
                    level=EscalationLevel.INVOKE_TEAM_LEAD,
                    retry_count=ctx.retry_count,
                    max_retries=ctx.max_retries,
                    feedback=self._build_feedback(ctx),
                )

        if ctx.team_lead_invoked and not ctx.engineering_manager_invoked:
            return EscalationDecision(
                level=EscalationLevel.INVOKE_ENGINEERING_MANAGER,
                retry_count=ctx.retry_count,
                max_retries=ctx.max_retries,
                team_lead_exhausted=True,
                feedback=self._build_feedback(ctx),
            )

        return EscalationDecision(
            level=EscalationLevel.HUMAN_ESCALATION,
            retry_count=ctx.retry_count,
            max_retries=ctx.max_retries,
            team_lead_exhausted=True,
            engineering_manager_exhausted=True,
            feedback=self._build_feedback(ctx),
        )

    def reset(self, step_name: str) -> None:
        """Reset the failure context for a step (after successful completion)."""
        self._contexts.pop(step_name, None)

    def _build_feedback(self, ctx: FailureContext) -> str:
        if not ctx.failure_outputs or not ctx.feedback_injection:
            return ""
        last = ctx.failure_outputs[-1]
        return f"Previous attempt failed:\n{last[:500]}"
