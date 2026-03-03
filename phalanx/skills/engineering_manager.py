"""Outer Loop — Engineering Manager for the 3-Loop Adaptive Control architecture.

The Engineering Manager activates when the Middle Loop (Team Lead) escalates, or when
systemic infrastructure failures occur (repeated ghost sessions, API rate
limit storms, etc.).

Capabilities:
  - DAG restructuring (add, remove, reorder remaining steps)
  - Model swapping for specific agents
  - Team reconfiguration (add/remove workers, change timeouts)
  - Pause & clean (halt team, fix corrupted state, resume)
  - Human escalation (last resort)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum

from phalanx.skills.orchestrator import build_dag, modify_dag

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
    def from_dict(cls, d: dict) -> EngineeringManagerDecision:
        try:
            action = EngineeringManagerAction(d["action"])
        except (KeyError, ValueError):
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
        if self.action == EngineeringManagerAction.MODIFY_DAG and not self.dag_changes:
            errors.append("modify_dag action requires non-empty dag_changes")
        if self.action == EngineeringManagerAction.SWAP_MODEL and not self.model_changes:
            errors.append("swap_model action requires non-empty model_changes")
        return errors


def build_engineering_manager_prompt(
    remaining_steps: list[dict],
    completed_steps: list[dict],
    escalation_context: str,
    can_modify: list[str] | None = None,
    team_state: dict | None = None,
) -> str:
    """Build the prompt for an engineering manager step.

    Includes the remaining DAG, completed work, escalation chain context,
    and available modification operations.
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
        prompt += f"```json\n{json.dumps(team_state, indent=2, default=str)}\n```\n\n"

    prompt += "## Completed Steps\n"
    if completed_steps:
        for step in completed_steps:
            prompt += f"- {step.get('name', 'unnamed')}: completed\n"
    else:
        prompt += "(none)\n"

    scope_note = ""
    if can_modify:
        scope_note = f" (scoped to: {', '.join(can_modify)})"
    prompt += f"\n## Remaining Steps{scope_note}\n"
    if remaining_steps:
        prompt += f"```json\n{json.dumps(remaining_steps, indent=2)}\n```\n"
    else:
        prompt += "(none)\n"

    prompt += (
        "\n## Available Actions\n"
        "- **modify_dag**: Add, remove, reorder, or modify remaining steps\n"
        "- **swap_model**: Change the backend model for specific agents\n"
        "- **reconfigure_team**: Add/remove workers, change roles, adjust timeouts\n"
        "- **pause_and_clean**: Pause team, clean corrupted state, resume safely\n"
        "- **escalate_to_human**: Produce escalation artifact for human intervention\n"
        "\n## Instructions\n"
        "Analyze the escalation context and team state. Select the best action. "
        "Return your decision as a JSON object with fields: `action`, `rationale`, "
        "and the relevant change fields (`dag_changes`, `model_changes`, or "
        "`team_changes`).\n"
    )

    return prompt


def parse_engineering_manager_response(response_text: str) -> EngineeringManagerDecision:
    """Parse an engineering manager's LLM response into a structured decision.

    Falls back to 'escalate_to_human' if the response is unparseable.
    """
    try:
        start = response_text.index("{")
        end = response_text.rindex("}") + 1
        data = json.loads(response_text[start:end])
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


def apply_engineering_manager_decision(
    decision: EngineeringManagerDecision,
    db,
    team_id: str,
) -> dict:
    """Apply a validated EngineeringManagerDecision to the team state.

    Returns a summary of what was changed.
    """
    result = {"action": decision.action.value, "applied": False, "detail": ""}

    if decision.action == EngineeringManagerAction.MODIFY_DAG:
        active_run = db.get_active_skill_run(team_id)
        if active_run and active_run.get("dag_json"):
            try:
                dag_data = json.loads(active_run["dag_json"])
                steps_data = dag_data.get("steps", {})
                step_list = [{**v, "name": k} for k, v in steps_data.items()]
                dag = build_dag(step_list)
                for name in dag_data.get("completed", []):
                    dag.completed.add(name)
                dag.step_results = dag_data.get("step_results", {})

                dag = modify_dag(dag, decision.dag_changes)
                db.update_skill_run(active_run["id"], dag_json=dag.to_json())
            except Exception as e:
                logger.error("Failed to apply DAG changes: %s", e)
                result["detail"] = f"DAG modification failed: {e}"
                return result

        result["applied"] = True
        result["detail"] = f"Modified {len(decision.dag_changes)} DAG steps"
        db.log_event(
            team_id,
            "engineering_manager_applied",
            payload={
                "action": "modify_dag",
                "changes": decision.dag_changes,
                "rationale": decision.rationale,
            },
        )

    elif decision.action == EngineeringManagerAction.SWAP_MODEL:
        for agent_id, new_model in decision.model_changes.items():
            try:
                db.update_agent(agent_id, model=new_model)
            except Exception as e:
                logger.error("Failed to swap model for %s: %s", agent_id, e)
        result["applied"] = True
        result["detail"] = f"Swapped models for {len(decision.model_changes)} agents"
        db.log_event(
            team_id,
            "engineering_manager_applied",
            payload={
                "action": "swap_model",
                "model_changes": decision.model_changes,
                "rationale": decision.rationale,
            },
        )

    elif decision.action == EngineeringManagerAction.RECONFIGURE_TEAM:
        result["applied"] = True
        result["detail"] = "Team reconfigured"
        db.log_event(
            team_id,
            "engineering_manager_applied",
            payload={
                "action": "reconfigure_team",
                "changes": decision.team_changes,
                "rationale": decision.rationale,
            },
        )

    elif decision.action == EngineeringManagerAction.PAUSE_AND_CLEAN:
        db.update_team_status(team_id, "paused")
        result["applied"] = True
        result["detail"] = "Team paused for cleanup"
        db.log_event(
            team_id,
            "engineering_manager_applied",
            payload={
                "action": "pause_and_clean",
                "rationale": decision.rationale,
            },
        )

    elif decision.action == EngineeringManagerAction.ESCALATE_TO_HUMAN:
        result["applied"] = True
        result["detail"] = "Escalated to human"
        db.log_event(
            team_id,
            "human_escalation",
            payload={"rationale": decision.rationale},
        )

    return result
