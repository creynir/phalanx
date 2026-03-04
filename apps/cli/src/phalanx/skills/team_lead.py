"""Team Lead (Middle Loop) skill for adaptive control.

The Team Lead evaluates worker step failures and selects a recovery strategy.
It operates without a DAG in Phase 1.1 — strategies are applied to the plain
worker task context rather than DAG StepSpecs.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phalanx.db import StateDB

logger = logging.getLogger(__name__)


class TeamLeadStrategy(str, Enum):
    ADAPT_APPROACH = "adapt_approach"
    SPLIT_TASK = "split_task"
    RESCOPE = "rescope"
    ACCEPT_WITH_DEBT = "accept_with_debt"
    ESCALATE = "escalate"


STRATEGY_MENU = {
    TeamLeadStrategy.ADAPT_APPROACH: ("Modify the approach and retry with revised instructions"),
    TeamLeadStrategy.SPLIT_TASK: ("Break the task into smaller sub-tasks and retry"),
    TeamLeadStrategy.RESCOPE: ("Reduce the scope of the task to something achievable"),
    TeamLeadStrategy.ACCEPT_WITH_DEBT: ("Accept the partial result and record a debt item"),
    TeamLeadStrategy.ESCALATE: ("Escalate to the Engineering Manager (Outer Loop)"),
}


@dataclass
class DebtRecord:
    """A typed compromise/debt record created by team lead decisions."""

    team_id: str
    agent_id: str
    severity: str = "medium"
    category: str = "workaround"
    description: str = ""
    proposed_resolution: str | None = None
    skill_run_id: str | None = None
    step_name: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)

    VALID_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
    VALID_CATEGORIES = frozenset({"scope_reduction", "workaround", "deferred_test", "deferred_fix"})

    def validate(self) -> list[str]:
        errors = []
        if self.severity not in self.VALID_SEVERITIES:
            errors.append(
                f"Invalid severity '{self.severity}'. "
                f"Must be one of: {sorted(self.VALID_SEVERITIES)}"
            )
        if self.category not in self.VALID_CATEGORIES:
            errors.append(
                f"Invalid category '{self.category}'. "
                f"Must be one of: {sorted(self.VALID_CATEGORIES)}"
            )
        if not self.description:
            errors.append("description must not be empty")
        return errors

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "skill_run_id": self.skill_run_id,
            "step_name": self.step_name,
            "agent_id": self.agent_id,
            "severity": self.severity,
            "category": self.category,
            "description": self.description,
            "proposed_resolution": self.proposed_resolution,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DebtRecord":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            team_id=d.get("team_id", ""),
            agent_id=d.get("agent_id", ""),
            severity=d.get("severity", "medium"),
            category=d.get("category", "workaround"),
            description=d.get("description", ""),
            proposed_resolution=d.get("proposed_resolution"),
            skill_run_id=d.get("skill_run_id"),
            step_name=d.get("step_name"),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class TeamLeadDecision:
    """Structured output from a team lead step."""

    strategy: TeamLeadStrategy
    rationale: str = ""
    modified_step_specs: list[dict] | None = None
    debt_record: DebtRecord | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "strategy": self.strategy.value,
            "rationale": self.rationale,
        }
        if self.modified_step_specs is not None:
            d["modified_step_specs"] = self.modified_step_specs
        if self.debt_record is not None:
            d["debt_record"] = self.debt_record.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TeamLeadDecision":
        strategy = TeamLeadStrategy(d.get("strategy", TeamLeadStrategy.ESCALATE))
        debt_raw = d.get("debt_record")
        debt = DebtRecord.from_dict(debt_raw) if debt_raw else None
        return cls(
            strategy=strategy,
            rationale=d.get("rationale", ""),
            modified_step_specs=d.get("modified_step_specs"),
            debt_record=debt,
        )


def build_team_lead_prompt(
    task_description: str,
    failure_outputs: list[str],
    retry_count: int,
    max_retries: int,
    worker_context: dict | None = None,
) -> str:
    """Build the prompt for a team lead intervention.

    In Phase 1.1 this works with plain worker task context rather than
    DAG StepSpecs, since the DAG orchestrator is deferred to Phase 1.2.
    """
    menu = "\n".join(f"- **{s.value}**: {desc}" for s, desc in STRATEGY_MENU.items())

    prompt = "# Team Lead Decision Required\n\n"
    prompt += "A worker has exhausted its retries and requires your intervention.\n\n"
    prompt += "## Task Description\n"
    prompt += f"```\n{task_description}\n```\n\n"

    if worker_context:
        prompt += "## Worker Context\n"
        prompt += f"```json\n{json.dumps(worker_context, indent=2)}\n```\n\n"

    prompt += f"## Failure History ({retry_count}/{max_retries} retries exhausted)\n\n"
    for i, output in enumerate(failure_outputs, 1):
        prompt += f"### Attempt {i}\n```\n{output}\n```\n"

    prompt += f"\n## Available Strategies\n{menu}\n"
    prompt += (
        "\n## Instructions\n"
        "Analyze the failure chain above and select the best strategy. "
        "Return your decision as a JSON object with fields: `strategy`, `rationale`, "
        "and optionally `modified_step_specs` or `debt_record`.\n"
    )
    return prompt


def apply_team_lead_decision(
    decision: TeamLeadDecision,
    db: "StateDB",
    team_id: str,
    agent_id: str,
    skill_run_id: str | None = None,
    step_name: str | None = None,
) -> dict:
    """Apply a TeamLeadDecision in a non-DAG environment.

    Returns a summary dict with keys: strategy, applied, detail.
    """
    result: dict = {"strategy": decision.strategy.value, "applied": False, "detail": ""}

    if decision.strategy == TeamLeadStrategy.ADAPT_APPROACH:
        result["applied"] = True
        result["detail"] = (
            f"Adapted approach: {decision.rationale}. "
            "Worker should retry with revised instructions."
        )

    elif decision.strategy == TeamLeadStrategy.SPLIT_TASK:
        result["applied"] = True
        result["detail"] = f"Task split requested: {decision.rationale}. Revised sub-tasks: " + str(
            decision.modified_step_specs or []
        )

    elif decision.strategy == TeamLeadStrategy.RESCOPE:
        result["applied"] = True
        result["detail"] = f"Rescoped task: {decision.rationale}"

    elif decision.strategy == TeamLeadStrategy.ACCEPT_WITH_DEBT:
        result["applied"] = True
        result["detail"] = f"Accepted with debt: {decision.rationale}"

        if decision.debt_record:
            debt = decision.debt_record
            errors = debt.validate()
            if errors:
                logger.warning("Invalid debt record: %s", errors)
            else:
                try:
                    db.create_debt_record(
                        debt_id=debt.id,
                        team_id=team_id,
                        agent_id=agent_id,
                        severity=debt.severity,
                        category=debt.category,
                        description=debt.description,
                        skill_run_id=skill_run_id,
                        step_name=step_name,
                        proposed_resolution=debt.proposed_resolution,
                    )
                    debt.created_at = time.time()
                except Exception as e:
                    logger.warning("Failed to persist debt record: %s", e)
        else:
            try:
                db.create_debt_record(
                    debt_id=str(uuid.uuid4())[:8],
                    team_id=team_id,
                    agent_id=agent_id,
                    severity="medium",
                    category="workaround",
                    description=decision.rationale or "Team lead accepted failure with debt",
                    skill_run_id=skill_run_id,
                    step_name=step_name,
                )
            except Exception as e:
                logger.warning("Failed to persist debt record: %s", e)

    elif decision.strategy == TeamLeadStrategy.ESCALATE:
        result["applied"] = True
        result["detail"] = "Escalated to Engineering Manager (Outer Loop)"
        try:
            db.create_engineering_manager_entry(
                team_id=team_id,
                trigger_source="team_lead_escalation",
                skill_run_id=skill_run_id,
            )
            db.log_event(
                team_id,
                "team_lead_decision",
                agent_id=agent_id,
                payload={"strategy": "escalate", "rationale": decision.rationale},
            )
        except Exception as e:
            logger.warning("Failed to log escalation: %s", e)

    return result


def parse_team_lead_response(response_text: str) -> TeamLeadDecision:
    """Parse a team lead's LLM response into a structured decision.

    Falls back to 'escalate' if the response is unparseable.
    """
    try:
        start = response_text.index("{")
        end = response_text.rindex("}")
        data = json.loads(response_text[start : end + 1])
        return TeamLeadDecision.from_dict(data)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse team lead response: %s", e)
        return TeamLeadDecision(
            strategy=TeamLeadStrategy.ESCALATE,
            rationale=f"Team lead response unparseable — auto-escalating. Error: {e}",
        )
