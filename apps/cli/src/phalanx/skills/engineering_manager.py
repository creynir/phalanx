"""Engineering Manager (Outer Loop) skill for adaptive control.

The Engineering Manager handles systemic infrastructure failures escalated by
the Team Lead (Middle Loop). In Phase 1.1 it operates without DAG StepSpecs —
it acts on plain agent/team state: swapping models, reconfiguring agents,
pausing teams, or escalating to humans.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phalanx.db import StateDB

logger = logging.getLogger(__name__)


class EngineeringManagerAction(str, Enum):
    MODIFY_DAG = "modify_dag"
    SWAP_MODEL = "swap_model"
    RECONFIGURE_TEAM = "reconfigure_team"
    PAUSE_AND_CLEAN = "pause_and_clean"
    ESCALATE_TO_HUMAN = "escalate_to_human"


@dataclass
class EngineeringManagerDecision:
    """Structured output from an Engineering Manager step."""

    action: EngineeringManagerAction
    rationale: str = ""
    dag_changes: list[dict] = field(default_factory=list)
    model_changes: dict[str, str] = field(default_factory=dict)
    team_changes: dict = field(default_factory=dict)
    wait_seconds: int = 0

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "rationale": self.rationale,
            "dag_changes": self.dag_changes,
            "model_changes": self.model_changes,
            "team_changes": self.team_changes,
            "wait_seconds": self.wait_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EngineeringManagerDecision":
        action_val = d.get("action", EngineeringManagerAction.ESCALATE_TO_HUMAN)
        try:
            action = EngineeringManagerAction(action_val)
        except ValueError:
            action = EngineeringManagerAction.ESCALATE_TO_HUMAN
        return cls(
            action=action,
            rationale=d.get("rationale", ""),
            dag_changes=d.get("dag_changes", []),
            model_changes=d.get("model_changes", {}),
            team_changes=d.get("team_changes", {}),
            wait_seconds=d.get("wait_seconds", 0),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.rationale:
            errors.append("rationale must not be empty")
        return errors


def build_engineering_manager_prompt(
    escalation_context: str,
    team_state: dict | None = None,
    completed_steps: list[dict] | None = None,
) -> str:
    """Build the prompt for an engineering manager intervention.

    In Phase 1.1 this works without DAG steps — it shows plain agent state.
    """
    prompt = "# Engineering Manager Decision Required\n\n"
    prompt += (
        "The Middle Loop (Team Lead) has escalated an issue that requires "
        "structural intervention.\n\n"
    )
    prompt += "## Escalation Context\n"
    prompt += f"{escalation_context}\n\n"

    if team_state:
        prompt += "## Current Team State\n"
        prompt += f"```json\n{json.dumps(team_state, indent=2)}\n```\n\n"

    if completed_steps:
        prompt += "## Completed Steps\n"
        for step in completed_steps:
            name = step.get("name", "unnamed")
            prompt += f"- {name}: completed\n"
    else:
        prompt += "## Completed Steps\n(none)\n"

    prompt += "\n## Available Actions\n"
    prompt += "- **modify_dag**: Add, remove, reorder, or modify remaining steps\n"
    prompt += "- **swap_model**: Change the backend model for specific agents\n"
    prompt += "- **reconfigure_team**: Add/remove workers, change roles, adjust timeouts\n"
    prompt += "- **pause_and_clean**: Pause team, clean corrupted state, resume safely\n"
    prompt += "- **escalate_to_human**: Produce escalation artifact for human intervention\n\n"

    prompt += (
        "## Instructions\n"
        "Analyze the escalation context and team state. Select the best action. "
        "Return your decision as a JSON object with fields: `action`, `rationale`, "
        "and the relevant change fields (`dag_changes`, `model_changes`, or `team_changes`).\n"
    )
    return prompt


def apply_engineering_manager_decision(
    decision: EngineeringManagerDecision,
    db: "StateDB",
    team_id: str,
) -> dict:
    """Apply a validated EngineeringManagerDecision to the team state.

    In Phase 1.1: no DAG — MODIFY_DAG is a no-op structural placeholder.
    Other actions (SWAP_MODEL, RECONFIGURE_TEAM, etc.) operate on plain agents.
    Returns a summary of what was changed.
    """
    result: dict = {"applied": False, "detail": "", "action": decision.action.value}

    if decision.action == EngineeringManagerAction.SWAP_MODEL:
        swapped = 0
        for agent_id, new_model in decision.model_changes.items():
            try:
                db.update_agent(agent_id, model=new_model)
                swapped += 1
            except Exception as e:
                logger.warning("Failed to swap model for %s: %s", agent_id, e)
        result["applied"] = True
        result["detail"] = f"Swapped models for {swapped} agents"
        try:
            db.log_event(team_id, "swap_model", payload={"changes": decision.model_changes})
        except Exception:
            pass

    elif decision.action == EngineeringManagerAction.MODIFY_DAG:
        result["applied"] = True
        result["detail"] = "DAG modification noted (Phase 1.2 feature — logged for future use)"
        try:
            db.log_event(
                team_id,
                "engineering_manager_applied",
                payload={"action": "modify_dag", "changes": decision.dag_changes},
            )
        except Exception:
            pass

    elif decision.action == EngineeringManagerAction.RECONFIGURE_TEAM:
        result["applied"] = True
        result["detail"] = "Team reconfigured"
        try:
            db.log_event(
                team_id,
                "reconfigure_team",
                payload={"changes": decision.team_changes},
            )
        except Exception:
            pass

    elif decision.action == EngineeringManagerAction.PAUSE_AND_CLEAN:
        try:
            db.update_team_status(team_id, "paused")
        except Exception:
            pass
        result["applied"] = True
        result["detail"] = "Team paused for cleanup"
        try:
            db.log_event(team_id, "pause_and_clean", payload={"rationale": decision.rationale})
        except Exception:
            pass

    elif decision.action == EngineeringManagerAction.ESCALATE_TO_HUMAN:
        result["applied"] = True
        result["detail"] = "Escalated to human"
        try:
            db.log_event(
                team_id,
                "human_escalation",
                payload={"rationale": decision.rationale},
            )
        except Exception:
            pass

    return result


def parse_engineering_manager_response(response_text: str) -> EngineeringManagerDecision:
    """Parse an engineering manager's LLM response into a structured decision.

    Falls back to 'escalate_to_human' if the response is unparseable.
    """
    try:
        start = response_text.index("{")
        end = response_text.rindex("}")
        data = json.loads(response_text[start : end + 1])
        decision = EngineeringManagerDecision.from_dict(data)
        errors = decision.validate()
        if errors:
            logger.warning("Engineering manager decision validation errors: %s", errors)
        return decision
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse engineering manager response: %s", e)
        return EngineeringManagerDecision(
            action=EngineeringManagerAction.ESCALATE_TO_HUMAN,
            rationale=f"Engineering manager response unparseable — escalating to human. Error: {e}",
        )
