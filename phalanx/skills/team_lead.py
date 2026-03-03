"""Middle Loop — Team Lead step type for the 3-Loop Adaptive Control architecture.

The Team Lead activates when a worker step exhausts its retries and escalates.
It analyzes the failure chain and selects a recovery strategy from the
Typed Strategy Menu.

Strategies:
  adapt_approach   — modify the step spec and re-queue with a different prompt
  split_task       — replace the failed step with multiple sub-steps
  rescope          — reduce scope and document the reduction as debt
  accept_with_debt — mark the failure as accepted debt, continue past it
  escalate         — escalate to the Outer Loop (Engineering Manager)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TeamLeadStrategy(str, Enum):
    ADAPT_APPROACH = "adapt_approach"
    SPLIT_TASK = "split_task"
    RESCOPE = "rescope"
    ACCEPT_WITH_DEBT = "accept_with_debt"
    ESCALATE = "escalate"


STRATEGY_MENU = list(TeamLeadStrategy)


@dataclass
class DebtRecord:
    """A typed compromise/debt record created by team lead decisions."""

    id: str = field(default_factory=lambda: f"debt-{uuid.uuid4().hex[:8]}")
    team_id: str = ""
    skill_run_id: str | None = None
    step_name: str | None = None
    agent_id: str = ""
    severity: str = "medium"  # low, medium, high, critical
    category: str = "workaround"  # scope_reduction, workaround, deferred_test, deferred_fix
    description: str = ""
    proposed_resolution: str | None = None
    created_at: float = 0.0

    VALID_SEVERITIES = ("low", "medium", "high", "critical")
    VALID_CATEGORIES = ("scope_reduction", "workaround", "deferred_test", "deferred_fix")

    def validate(self) -> list[str]:
        errors = []
        if self.severity not in self.VALID_SEVERITIES:
            errors.append(f"Invalid severity '{self.severity}'")
        if self.category not in self.VALID_CATEGORIES:
            errors.append(f"Invalid category '{self.category}'")
        if not self.description:
            errors.append("Description is required")
        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DebtRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class TeamLeadDecision:
    """Structured output from a team lead step."""

    strategy: TeamLeadStrategy
    rationale: str = ""
    modified_step_specs: list[dict] | None = None
    debt_record: DebtRecord | None = None

    def to_dict(self) -> dict:
        d = {
            "strategy": self.strategy.value,
            "rationale": self.rationale,
        }
        if self.modified_step_specs is not None:
            d["modified_step_specs"] = self.modified_step_specs
        if self.debt_record is not None:
            d["debt_record"] = self.debt_record.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TeamLeadDecision:
        try:
            strategy = TeamLeadStrategy(d["strategy"])
        except (KeyError, ValueError):
            strategy = TeamLeadStrategy.ESCALATE

        debt = None
        if d.get("debt_record"):
            debt = DebtRecord.from_dict(d["debt_record"])

        return cls(
            strategy=strategy,
            rationale=d.get("rationale", ""),
            modified_step_specs=d.get("modified_step_specs"),
            debt_record=debt,
        )


def build_team_lead_prompt(
    step_spec: dict,
    failure_outputs: list[str],
    retry_count: int,
    max_retries: int,
    strategy_menu: list[str] | None = None,
) -> str:
    """Build the prompt for a team lead step.

    Includes the original step spec, all retry failure outputs,
    and the available strategy menu.
    """
    menu = strategy_menu or [s.value for s in STRATEGY_MENU]

    prompt = "# Team Lead Decision Required\n\n"
    prompt += "A worker step has exhausted its retries and requires your intervention.\n\n"

    prompt += "## Original Step Specification\n"
    prompt += f"```json\n{json.dumps(step_spec, indent=2)}\n```\n\n"

    prompt += f"## Failure History ({retry_count}/{max_retries} retries exhausted)\n\n"
    for i, output in enumerate(failure_outputs, 1):
        prompt += f"### Attempt {i}\n```\n{output[:2000]}\n```\n\n"

    prompt += "## Available Strategies\n"
    for s in menu:
        prompt += f"- **{s}**\n"

    prompt += (
        "\n## Instructions\n"
        "Analyze the failure chain above and select the best strategy. "
        "Return your decision as a JSON object with fields: "
        "`strategy`, `rationale`, and optionally `modified_step_specs` "
        "or `debt_record`.\n"
    )

    return prompt


def apply_team_lead_decision(
    decision: TeamLeadDecision,
    dag,
    db,
    team_id: str,
    skill_run_id: str | None = None,
    step_name: str | None = None,
) -> dict:
    """Apply a TeamLeadDecision to the running DAG and persist debt if created.

    Returns a summary dict with keys: strategy, applied, detail.
    """
    from phalanx.skills.orchestrator import modify_dag, CyclicDependencyError

    result = {"strategy": decision.strategy.value, "applied": False, "detail": ""}

    if decision.strategy == TeamLeadStrategy.ADAPT_APPROACH:
        if decision.modified_step_specs:
            changes = [
                {"op": "modify", "name": step_name, "updates": spec}
                for spec in decision.modified_step_specs
                if step_name
            ]
            if changes:
                try:
                    modify_dag(dag, changes)
                    result["applied"] = True
                    result["detail"] = f"Adapted approach for step '{step_name}'"
                except CyclicDependencyError as e:
                    result["detail"] = f"Adaptation rejected: {e}"

    elif decision.strategy == TeamLeadStrategy.SPLIT_TASK:
        if decision.modified_step_specs:
            changes = [{"op": "remove", "name": step_name}] if step_name else []
            for spec in decision.modified_step_specs:
                changes.append({"op": "add", "step": spec})
            try:
                modify_dag(dag, changes)
                result["applied"] = True
                result["detail"] = (
                    f"Split '{step_name}' into {len(decision.modified_step_specs)} sub-steps"
                )
            except CyclicDependencyError as e:
                result["detail"] = f"Split rejected: {e}"

    elif decision.strategy == TeamLeadStrategy.RESCOPE:
        if decision.modified_step_specs and step_name:
            changes = [
                {"op": "modify", "name": step_name, "updates": decision.modified_step_specs[0]}
            ]
            try:
                modify_dag(dag, changes)
                result["applied"] = True
                result["detail"] = f"Rescoped step '{step_name}'"
            except CyclicDependencyError as e:
                result["detail"] = f"Rescope rejected: {e}"

        if decision.debt_record is None:
            decision.debt_record = DebtRecord(
                team_id=team_id,
                skill_run_id=skill_run_id,
                step_name=step_name,
                severity="medium",
                category="scope_reduction",
                description=decision.rationale or f"Rescoped step '{step_name}'",
            )

    elif decision.strategy == TeamLeadStrategy.ACCEPT_WITH_DEBT:
        result["applied"] = True
        result["detail"] = f"Accepted failure as debt for step '{step_name}'"
        if decision.debt_record is None:
            decision.debt_record = DebtRecord(
                team_id=team_id,
                skill_run_id=skill_run_id,
                step_name=step_name,
                severity="medium",
                category="workaround",
                description=decision.rationale or f"Accepted debt for step '{step_name}'",
            )

    elif decision.strategy == TeamLeadStrategy.ESCALATE:
        result["applied"] = True
        result["detail"] = "Escalated to Outer Loop (Engineering Manager)"

    if decision.debt_record:
        errors = decision.debt_record.validate()
        if not errors:
            try:
                import time

                decision.debt_record.created_at = time.time()
                decision.debt_record.team_id = team_id
                db.create_debt_record(
                    debt_id=decision.debt_record.id,
                    team_id=team_id,
                    agent_id=decision.debt_record.agent_id or "team_lead",
                    severity=decision.debt_record.severity,
                    category=decision.debt_record.category,
                    description=decision.debt_record.description,
                    skill_run_id=skill_run_id,
                    step_name=step_name,
                    proposed_resolution=decision.debt_record.proposed_resolution,
                )
            except Exception as e:
                logger.warning("Failed to persist debt record: %s", e)
        else:
            logger.warning("Invalid debt record: %s", errors)

    db.log_event(
        team_id,
        "team_lead_decision",
        payload={
            "strategy": decision.strategy.value,
            "rationale": decision.rationale,
            "applied": result["applied"],
        },
    )

    return result


def parse_team_lead_response(response_text: str) -> TeamLeadDecision:
    """Parse a team lead's LLM response into a structured decision.

    Falls back to 'escalate' if the response is unparseable.
    """
    try:
        start = response_text.index("{")
        end = response_text.rindex("}") + 1
        data = json.loads(response_text[start:end])
        return TeamLeadDecision.from_dict(data)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse team lead response: %s", e)
        return TeamLeadDecision(
            strategy=TeamLeadStrategy.ESCALATE,
            rationale=f"Team lead response unparseable — auto-escalating. Error: {e}",
        )
