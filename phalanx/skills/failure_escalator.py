"""Failure Escalation Chain for the 3-Loop Adaptive Control architecture.

Routes failures through the escalation chain:
  Inner Loop (retry with feedback) → Middle Loop (team lead) → Outer Loop (engineering manager) → Human

The FailureEscalator decides at each level whether to retry, invoke the
team lead, invoke the engineering manager, or escalate to human.
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
    """Accumulated context about a step failure across retries."""

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
    """Routes step failures through the 3-loop escalation chain."""

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

    def record_failure(self, step_name: str, output: str) -> None:
        """Record a step failure output."""
        ctx = self._contexts.get(step_name)
        if ctx:
            ctx.add_failure(output)

    def decide(self, step_name: str) -> EscalationDecision:
        """Determine the next escalation action for a failed step."""
        ctx = self._contexts.get(step_name)
        if ctx is None:
            return EscalationDecision(level=EscalationLevel.HUMAN_ESCALATION)

        if ctx.retry_count < ctx.max_retries:
            feedback = None
            if ctx.feedback_injection and ctx.failure_outputs:
                feedback = self._build_feedback(ctx)
            return EscalationDecision(
                level=EscalationLevel.RETRY,
                retry_count=ctx.retry_count,
                max_retries=ctx.max_retries,
                feedback=feedback,
            )

        if not ctx.team_lead_invoked:
            ctx.team_lead_invoked = True
            return EscalationDecision(
                level=EscalationLevel.INVOKE_TEAM_LEAD,
                retry_count=ctx.retry_count,
                max_retries=ctx.max_retries,
                feedback=self._build_feedback(ctx),
            )

        if not ctx.engineering_manager_invoked:
            ctx.engineering_manager_invoked = True
            return EscalationDecision(
                level=EscalationLevel.INVOKE_ENGINEERING_MANAGER,
                retry_count=ctx.retry_count,
                max_retries=ctx.max_retries,
                feedback=self._build_feedback(ctx),
                team_lead_exhausted=True,
            )

        return EscalationDecision(
            level=EscalationLevel.HUMAN_ESCALATION,
            retry_count=ctx.retry_count,
            max_retries=ctx.max_retries,
            team_lead_exhausted=True,
            engineering_manager_exhausted=True,
        )

    def reset(self, step_name: str) -> None:
        """Reset failure context for a step (after successful recovery)."""
        self._contexts.pop(step_name, None)

    def _build_feedback(self, ctx: FailureContext) -> str:
        """Build feedback injection text from failure history."""
        if not ctx.failure_outputs:
            return ""

        parts = [
            f"This is retry {ctx.retry_count} of {ctx.max_retries} "
            f"— learn from the previous failure(s).\n"
        ]
        for i, output in enumerate(ctx.failure_outputs[-3:], 1):
            parts.append(f"## Failure Attempt {i}\n```\n{output[:1500]}\n```\n")

        return "\n".join(parts)
