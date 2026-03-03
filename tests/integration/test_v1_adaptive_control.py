"""Integration tests for v1.0.0 3-Loop Adaptive Control — IT-099 through IT-124."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from phalanx.db import StateDB
from phalanx.skills.team_lead import (
    TeamLeadDecision,
    TeamLeadStrategy,
    DebtRecord,
    apply_team_lead_decision,
    build_team_lead_prompt,
    parse_team_lead_response,
)
from phalanx.skills.failure_escalator import (
    EscalationLevel,
    FailureEscalator,
)
from phalanx.skills.engineering_manager import (
    EngineeringManagerAction,
    EngineeringManagerDecision,
    apply_engineering_manager_decision,
    build_engineering_manager_prompt,
    parse_engineering_manager_response,
)
from phalanx.skills.orchestrator import (
    CyclicDependencyError,
    build_dag,
    mark_complete,
    modify_dag,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        db = StateDB(db_path=Path(td) / "state.db")
        db.create_team("t1", "test task")
        db.create_agent("w1", "t1", "code")
        yield db


# -- Inner Loop (IT-099 to IT-103) --


class TestIT099_RetryWithFeedback:
    """IT-099: Step fails with retries remaining. Failure output injected into retry prompt."""

    def test_retry_feedback(self):
        esc = FailureEscalator()
        esc.get_or_create_context("step1", max_retries=3)
        esc.record_failure("step1", "Error: file not found")
        decision = esc.decide("step1")
        assert decision.level == EscalationLevel.RETRY
        assert decision.feedback is not None
        assert "file not found" in decision.feedback


class TestIT100_FeedbackInjectionContent:
    """IT-100: Retry prompt contains original task, failure output, retry instruction."""

    def test_feedback_content(self):
        esc = FailureEscalator()
        esc.get_or_create_context("step1", max_retries=3)
        esc.record_failure("step1", "TypeError: cannot read property 'x'")
        decision = esc.decide("step1")
        assert "retry" in decision.feedback.lower()
        assert "TypeError" in decision.feedback
        assert decision.retry_count == 1


class TestIT101_RetryCounterPersistence:
    """IT-101: After crash during retry 2 of 3, resume restores counter to 2."""

    def test_counter_persistence(self):
        esc = FailureEscalator()
        ctx = esc.get_or_create_context("step1", max_retries=3)
        esc.record_failure("step1", "fail 1")
        esc.record_failure("step1", "fail 2")
        assert ctx.retry_count == 2
        decision = esc.decide("step1")
        assert decision.retry_count == 2
        assert decision.level == EscalationLevel.RETRY


class TestIT102_EscalateToTeamLead:
    """IT-102: Step exhausts max_retries. invoke_team_lead decision returned."""

    def test_escalate(self):
        esc = FailureEscalator()
        esc.get_or_create_context("step1", max_retries=2)
        esc.record_failure("step1", "fail 1")
        esc.record_failure("step1", "fail 2")
        decision = esc.decide("step1")
        assert decision.level == EscalationLevel.INVOKE_TEAM_LEAD


class TestIT103_FeedbackInjectionDisabled:
    """IT-103: Step with feedback_injection: false retries without injecting context."""

    def test_blind_retry(self):
        esc = FailureEscalator()
        esc.get_or_create_context("step1", max_retries=3, feedback_injection=False)
        esc.record_failure("step1", "fail 1")
        decision = esc.decide("step1")
        assert decision.level == EscalationLevel.RETRY
        assert decision.feedback is None


# -- Middle Loop / Team Lead (IT-104 to IT-111) --


class TestIT104_AdaptApproach:
    """IT-104: Team lead returns adapt_approach. Modified step specs fed back."""

    def test_adapt_approach(self, tmp_db):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": ["A"]},
        ]
        dag = build_dag(steps)

        decision = TeamLeadDecision(
            strategy=TeamLeadStrategy.ADAPT_APPROACH,
            rationale="Change prompt for better results",
            modified_step_specs=[{"prompt": "new approach"}],
        )
        result = apply_team_lead_decision(decision, dag, tmp_db, "t1", step_name="A")
        assert result["applied"] is True
        assert dag.steps["A"].prompt == "new approach"


class TestIT105_SplitTask:
    """IT-105: Team lead returns split_task. Original step replaced with sub-steps."""

    def test_split_task(self, tmp_db):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": ["A"]},
        ]
        dag = build_dag(steps)

        decision = TeamLeadDecision(
            strategy=TeamLeadStrategy.SPLIT_TASK,
            modified_step_specs=[
                {"name": "A1", "depends_on": []},
                {"name": "A2", "depends_on": ["A1"]},
            ],
        )
        result = apply_team_lead_decision(decision, dag, tmp_db, "t1", step_name="A")
        assert result["applied"] is True
        assert "A1" in dag.steps
        assert "A2" in dag.steps


class TestIT106_Rescope:
    """IT-106: Team lead returns rescope. Reduced scope replaces original."""

    def test_rescope(self, tmp_db):
        steps = [
            {"name": "A", "depends_on": [], "prompt": "full scope"},
            {"name": "B", "depends_on": ["A"]},
        ]
        dag = build_dag(steps)

        decision = TeamLeadDecision(
            strategy=TeamLeadStrategy.RESCOPE,
            rationale="Reduce scope to minimum viable",
            modified_step_specs=[{"prompt": "reduced scope"}],
        )
        result = apply_team_lead_decision(decision, dag, tmp_db, "t1", step_name="A")
        assert result["applied"] is True
        assert dag.steps["A"].prompt == "reduced scope"

        debt = tmp_db.get_team_debt("t1")
        assert len(debt) >= 1
        assert any(d["category"] == "scope_reduction" for d in debt)


class TestIT107_AcceptWithDebt:
    """IT-107: Team lead returns accept_with_debt. DebtRecord created."""

    def test_accept_with_debt(self, tmp_db):
        steps = [{"name": "A", "depends_on": []}]
        dag = build_dag(steps)

        debt = DebtRecord(
            team_id="t1",
            agent_id="w1",
            severity="high",
            category="workaround",
            description="Accepted test failure as known issue",
        )
        decision = TeamLeadDecision(
            strategy=TeamLeadStrategy.ACCEPT_WITH_DEBT,
            rationale="Known flaky test",
            debt_record=debt,
        )
        result = apply_team_lead_decision(decision, dag, tmp_db, "t1", step_name="A")
        assert result["applied"] is True

        records = tmp_db.get_team_debt("t1")
        assert len(records) >= 1
        assert records[0]["severity"] == "high"


class TestIT108_TeamLeadEscalate:
    """IT-108: Team lead escalates to outer loop. EngineeringManagerStep invoked."""

    def test_escalate(self, tmp_db):
        steps = [{"name": "A", "depends_on": []}]
        dag = build_dag(steps)

        decision = TeamLeadDecision(
            strategy=TeamLeadStrategy.ESCALATE,
            rationale="Cannot resolve — need structural change",
        )
        result = apply_team_lead_decision(decision, dag, tmp_db, "t1")
        assert result["applied"] is True
        assert "Outer Loop" in result["detail"]


class TestIT109_UnparseableResponse:
    """IT-109: Team lead LLM returns garbage. Default to escalate."""

    def test_garbage_response(self):
        decision = parse_team_lead_response("this is not json at all!!")
        assert decision.strategy == TeamLeadStrategy.ESCALATE
        assert "unparseable" in decision.rationale.lower()


class TestIT110_TeamLeadSoulTemplate:
    """IT-110: Team lead step loads correct team_lead_soul template."""

    def test_soul_template(self):
        prompt = build_team_lead_prompt(
            step_spec={"name": "deploy", "prompt": "deploy to prod"},
            failure_outputs=["Error: connection refused"],
            retry_count=3,
            max_retries=3,
        )
        assert "Team Lead Decision Required" in prompt
        assert "deploy" in prompt
        assert "connection refused" in prompt


class TestIT111_TeamLeadFullFailureChain:
    """IT-111: Team lead prompt includes original spec, all retry failures, count, menu."""

    def test_full_context(self):
        prompt = build_team_lead_prompt(
            step_spec={"name": "test", "type": "worker"},
            failure_outputs=["fail 1", "fail 2", "fail 3"],
            retry_count=3,
            max_retries=3,
        )
        assert "3/3" in prompt
        assert "Attempt 1" in prompt
        assert "Attempt 3" in prompt
        for strategy in ["adapt_approach", "split_task", "rescope", "accept_with_debt", "escalate"]:
            assert strategy in prompt


# -- Outer Loop / Engineering Manager (IT-112 to IT-124) --


class TestIT112_EngineeringManagerDAGModification:
    """IT-112: Engineering manager modifies step list. DAG updated without cycles."""

    def test_dag_modification(self, tmp_db):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": ["A"]},
        ]
        dag = build_dag(steps)
        mark_complete(dag, "A")

        decision = EngineeringManagerDecision(
            action=EngineeringManagerAction.MODIFY_DAG,
            rationale="Add validation step",
            dag_changes=[{"op": "add", "step": {"name": "validate", "depends_on": ["A"]}}],
        )
        result = apply_engineering_manager_decision(decision, tmp_db, "t1")
        assert result["applied"] is True


class TestIT113_EngineeringManagerCycleRejection:
    """IT-113: Engineering manager introduces cyclic dependency. Rejected and escalated."""

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


class TestIT114_EngineeringManagerStepRemoval:
    """IT-114: Engineering manager removes future step. Downstream re-wired."""

    def test_step_removal(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "B", "depends_on": ["A"]},
            {"name": "C", "depends_on": ["B"]},
        ]
        dag = build_dag(steps)
        modify_dag(dag, [{"op": "remove", "name": "B"}])
        assert "B" not in dag.steps
        assert "B" not in dag.steps["C"].depends_on


class TestIT115_EngineeringManagerStepAddition:
    """IT-115: Engineering manager adds new step between existing steps."""

    def test_step_addition(self):
        steps = [
            {"name": "A", "depends_on": []},
            {"name": "C", "depends_on": ["A"]},
        ]
        dag = build_dag(steps)
        modify_dag(
            dag,
            [
                {"op": "add", "step": {"name": "B", "depends_on": ["A"]}},
                {"op": "modify", "name": "C", "updates": {"depends_on": ["B"]}},
            ],
        )
        assert "B" in dag.steps
        assert dag.steps["C"].depends_on == ["B"]


class TestIT116_EngineeringManagerSoulTemplate:
    """IT-116: Engineering manager loads engineering_manager_soul with can_modify scope."""

    def test_soul_template(self):
        prompt = build_engineering_manager_prompt(
            remaining_steps=[{"name": "B"}, {"name": "C"}],
            completed_steps=[{"name": "A"}],
            escalation_context="Team lead could not resolve step B failure",
            can_modify=["B", "C"],
        )
        assert "Engineering Manager" in prompt
        assert "scoped to: B, C" in prompt


class TestIT117_EngineeringManagerContext:
    """IT-117: Engineering manager prompt includes remaining DAG, completed summary, escalation chain."""

    def test_context(self):
        prompt = build_engineering_manager_prompt(
            remaining_steps=[{"name": "B", "depends_on": ["A"]}],
            completed_steps=[{"name": "A"}],
            escalation_context="Step B failed 5 times with TypeError",
            team_state={"agents": [{"id": "w1", "status": "running"}]},
        )
        assert "A: completed" in prompt
        assert "TypeError" in prompt
        assert "remaining" in prompt.lower()
        assert "w1" in prompt


class TestIT118_HumanEscalationFallback:
    """IT-118: Engineering manager fails → escalation_required artifact with diagnostic info."""

    def test_human_escalation(self):
        decision = parse_engineering_manager_response("totally garbled output with no JSON")
        assert decision.action == EngineeringManagerAction.ESCALATE_TO_HUMAN
        assert "unparseable" in decision.rationale.lower()


class TestIT119_FullChain:
    """IT-119: Inner → team lead → engineering manager → DAG modification → execution continues."""

    def test_full_chain(self, tmp_db):
        esc = FailureEscalator()
        esc.get_or_create_context("deploy", max_retries=2)
        esc.record_failure("deploy", "fail 1")
        esc.record_failure("deploy", "fail 2")

        decision = esc.decide("deploy")
        assert decision.level == EscalationLevel.INVOKE_TEAM_LEAD

        team_lead_resp = json.dumps(
            {
                "strategy": "escalate",
                "rationale": "Need structural change",
            }
        )
        team_lead_dec = parse_team_lead_response(team_lead_resp)
        assert team_lead_dec.strategy == TeamLeadStrategy.ESCALATE

        replan_decision = esc.decide("deploy")
        assert replan_decision.level == EscalationLevel.INVOKE_ENGINEERING_MANAGER


class TestIT120_FullChainBufferCorruption:
    """IT-120: Buffer corruption → retry file-based → team lead adapts → success."""

    def test_buffer_corruption_chain(self, tmp_db):
        from phalanx.monitor.stall import _check_buffer_corrupted

        lines = ["quote> "]
        assert _check_buffer_corrupted(lines) is True

        team_lead_resp = json.dumps(
            {
                "strategy": "adapt_approach",
                "rationale": "Switch to file-based delivery",
                "modified_step_specs": [{"prompt": "use file delivery"}],
            }
        )
        decision = parse_team_lead_response(team_lead_resp)
        assert decision.strategy == TeamLeadStrategy.ADAPT_APPROACH


class TestIT121_FullChainTUICrash:
    """IT-121: TUI crash → retries → team lead sanitizes output → success."""

    def test_tui_crash_chain(self, tmp_db):
        from phalanx.monitor.stall import _check_process_exited

        lines = ["zsh: command not found: agent", "zsh: parse error near \\"]
        assert _check_process_exited(lines) is True

        team_lead_resp = json.dumps(
            {
                "strategy": "adapt_approach",
                "rationale": "Sanitize output, shorter prompts",
                "modified_step_specs": [{"prompt": "sanitized task"}],
            }
        )
        decision = parse_team_lead_response(team_lead_resp)
        assert decision.strategy == TeamLeadStrategy.ADAPT_APPROACH


class TestIT122_ModelSwapOnAPIFailure:
    """IT-122: Engineering manager swaps model on repeated API rate limit failures."""

    def test_model_swap(self, tmp_db):
        decision = EngineeringManagerDecision(
            action=EngineeringManagerAction.SWAP_MODEL,
            rationale="Rate limited on opus, switch to sonnet",
            model_changes={"w1": "claude-4-sonnet"},
        )
        result = apply_engineering_manager_decision(decision, tmp_db, "t1")
        assert result["applied"] is True
        agent = tmp_db.get_agent("w1")
        assert agent["model"] == "claude-4-sonnet"


class TestIT123_TeamPauseAndClean:
    """IT-123: Engineering manager pauses team, cleans corrupted state, resumes."""

    def test_pause_and_clean(self, tmp_db):
        decision = EngineeringManagerDecision(
            action=EngineeringManagerAction.PAUSE_AND_CLEAN,
            rationale="Corrupted state needs cleanup",
        )
        result = apply_engineering_manager_decision(decision, tmp_db, "t1")
        assert result["applied"] is True
        team = tmp_db.get_team("t1")
        assert team["status"] == "paused"


class TestIT124_DynamicTeamReconfiguration:
    """IT-124: Engineering manager adds new worker agent to running team."""

    def test_add_worker(self, tmp_db):
        decision = EngineeringManagerDecision(
            action=EngineeringManagerAction.RECONFIGURE_TEAM,
            rationale="Add extra worker for parallelism",
            team_changes={"add_workers": [{"role": "coder", "count": 1}]},
        )
        result = apply_engineering_manager_decision(decision, tmp_db, "t1")
        assert result["applied"] is True
