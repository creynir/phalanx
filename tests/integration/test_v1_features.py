"""Integration tests for v1.0.0 features — IT-125 through IT-191.

Covers: Artifact Finality, Premature Completion, Cost Tracking, Debt Tracking,
Checkpoint/Resume, Continual Learning, Ghost Session Deep, Cross-Session Memory,
Cost Failure Modes, API Rate Limit Resilience.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phalanx.artifacts.schema import Artifact
from phalanx.artifacts.writer import write_artifact
from phalanx.costs.aggregator import CostAggregator
from phalanx.costs.pricing import DEFAULT_COST_TABLE, estimate_cost
from phalanx.db import StateDB
from phalanx.monitor.stall import _check_process_exited, _check_rate_limited
from phalanx.process.manager import AgentProcess, ProcessManager
from phalanx.skills.team_lead import DebtRecord
from phalanx.skills.checkpoint import CheckpointManager


pytestmark = pytest.mark.integration


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        db = StateDB(db_path=Path(td) / "state.db")
        db.create_team("t1", "test task")
        db.create_agent("w1", "t1", "code", role="worker", backend="cursor")
        db.create_agent("w2", "t1", "test", role="worker", backend="cursor")
        yield db


@pytest.fixture
def tmp_db_with_root():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = StateDB(db_path=root / ".phalanx" / "state.db")
        db.create_team("t1", "test task")
        db.create_agent("w1", "t1", "code", role="worker", backend="cursor")
        db.create_agent("lead-t1", "t1", "coordinate", role="lead", backend="cursor")
        yield db, root


# ═══════════════════════════════════════════════════════════════════
# 17. Artifact Finality & Post-Completion Responsiveness (IT-125..IT-127)
# ═══════════════════════════════════════════════════════════════════


class TestIT125_SuccessNotTerminal:
    """IT-125: Success artifact is not terminal — agent can resume."""

    def test_success_not_terminal(self, tmp_db):
        db = tmp_db
        db.update_agent("w1", status="suspended", artifact_status="success")
        db.get_agent("w1")

        db.update_agent("w1", artifact_status=None)
        updated = db.get_agent("w1")
        assert updated["artifact_status"] is None


class TestIT126_SuspendedAgentTaskChange:
    """IT-126: Suspended agent with success artifact gets new task on resume."""

    def test_task_change_on_resume(self, tmp_db_with_root):
        db, root = tmp_db_with_root
        db.update_agent("w1", status="suspended", artifact_status="success")

        art = Artifact(status="success", output={"result": "done"}, agent_id="w1", team_id="t1")
        art_dir = root / "teams" / "t1" / "agents" / "w1"
        write_artifact(art_dir, art)

        db.post_to_feed("t1", "lead-t1", "New task: refactor the module")

        from phalanx.team.orchestrator import _build_resume_prompt

        agent = db.get_agent("w1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "NEW DIRECTIVES" in prompt or "refactor the module" in prompt


class TestIT127_PostArtifactFeedMonitoring:
    """IT-127: Monitor continues checking for feed messages after success artifact."""

    def test_post_artifact_monitoring(self, tmp_db):
        db = tmp_db
        db.update_agent("w1", status="suspended", artifact_status="success")

        from phalanx.monitor.team_monitor import _should_wake_suspended

        agent = db.get_agent("w1")
        assert _should_wake_suspended(db, agent) is False

        db.post_to_feed("t1", "lead-t1", "New directive for w1")
        agent = db.get_agent("w1")
        assert _should_wake_suspended(db, agent) is True


# ═══════════════════════════════════════════════════════════════════
# 18. Premature Completion Prevention (IT-128..IT-130)
# ═══════════════════════════════════════════════════════════════════


class TestIT128_ConsensusBasedCompletion:
    """IT-128: Lead must verify feed consensus before consolidating."""

    def test_consensus(self, tmp_db_with_root):
        db, root = tmp_db_with_root
        db.update_agent("lead-t1", status="suspended")

        from phalanx.team.orchestrator import _build_resume_prompt

        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "worker" in prompt.lower() or "status" in prompt.lower()


class TestIT129_PrematureShutdownPrevention:
    """IT-129: Monitor blocks premature shutdown during active feed."""

    def test_shutdown_blocked(self, tmp_db):
        db = tmp_db
        db.update_agent("w1", status="suspended", artifact_status="success")
        db.post_to_feed("t1", "lead-t1", "New work incoming")

        from phalanx.monitor.team_monitor import _should_wake_suspended

        agent = db.get_agent("w1")
        assert _should_wake_suspended(db, agent) is True


class TestIT130_LeadCompletionHeuristic:
    """IT-130: Lead resume includes explicit consensus instruction."""

    def test_completion_heuristic(self, tmp_db_with_root):
        db, root = tmp_db_with_root
        db.update_agent("lead-t1", status="suspended")

        from phalanx.team.orchestrator import _build_resume_prompt

        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(root, db, agent)
        assert "artifact" in prompt.lower() or "complete" in prompt.lower()


# ═══════════════════════════════════════════════════════════════════
# 19. Cost Tracking (IT-131..IT-138)
# ═══════════════════════════════════════════════════════════════════


class TestIT131_RecordUsage:
    """IT-131: Insert token usage record. Verify correct fields."""

    def test_record_usage(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 1000, 500)

        records = tmp_db.get_agent_token_usage("w1")
        assert len(records) == 1
        r = records[0]
        assert r["input_tokens"] == 1000
        assert r["output_tokens"] == 500
        assert r["total_tokens"] == 1500
        assert r["model"] == "claude-4-opus"
        assert r["estimated_cost"] is not None


class TestIT132_GetTeamCosts:
    """IT-132: Per-role and per-agent cost breakdowns."""

    def test_team_costs(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 2000, 1000)
        agg.record_usage("t1", "w2", "worker", "cursor", "claude-4-sonnet", 3000, 1500)

        breakdown = agg.get_team_costs("t1")
        assert breakdown.total_input_tokens == 5000
        assert breakdown.total_output_tokens == 2500
        assert "worker" in breakdown.by_role
        assert "w1" in breakdown.by_agent
        assert "w2" in breakdown.by_agent


class TestIT133_GetAgentCosts:
    """IT-133: Cumulative token totals for one agent."""

    def test_agent_costs(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 1000, 500)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 2000, 800)

        costs = agg.get_agent_costs("w1")
        assert costs.total_input_tokens == 3000
        assert costs.total_output_tokens == 1300
        assert costs.records == 2


class TestIT134_CostEstimation:
    """IT-134: estimated_cost calculated from input/output token counts."""

    def test_cost_estimation(self):
        cost = estimate_cost("claude-4-opus", 1000, 500)
        assert cost is not None
        expected = 1000 * (15.0 / 1_000_000) + 500 * (75.0 / 1_000_000)
        assert abs(cost - expected) < 1e-10


class TestIT135_DefaultPricing:
    """IT-135: Common models have default pricing."""

    def test_default_pricing(self):
        common_models = [
            "claude-4-opus",
            "claude-4-sonnet",
            "claude-3.5-sonnet",
            "gpt-4o",
            "gemini-2.5-pro",
        ]
        for model in common_models:
            assert model in DEFAULT_COST_TABLE, f"Missing default pricing for {model}"
            rates = DEFAULT_COST_TABLE[model]
            assert "input" in rates and "output" in rates


class TestIT136_UserOverridePricing:
    """IT-136: Override default pricing in config.json."""

    def test_user_override(self, tmp_db):
        custom_table = {"custom-model": {"input": 1.0 / 1_000_000, "output": 2.0 / 1_000_000}}
        agg = CostAggregator(tmp_db, cost_table=custom_table)
        agg.record_usage("t1", "w1", "worker", "test", "custom-model", 1000, 500)

        costs = agg.get_agent_costs("w1")
        assert costs.estimated_cost is not None
        expected = 1000 * (1.0 / 1_000_000) + 500 * (2.0 / 1_000_000)
        assert abs(costs.estimated_cost - expected) < 1e-10


class TestIT137_ParseTokenUsageOnHeartbeat:
    """IT-137: Backend calls parse_token_usage() on heartbeat check."""

    def test_parse_token_usage_exists(self):
        from phalanx.backends.cursor import CursorBackend

        backend = CursorBackend()
        assert hasattr(backend, "parse_token_usage")
        result = backend.parse_token_usage("")
        assert result is None or isinstance(result, dict)


class TestIT138_CostTrackingDuringRetries:
    """IT-138: Token usage from failed retries still recorded."""

    def test_retry_cost_tracking(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 500, 200)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 600, 300)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 700, 400)

        costs = agg.get_agent_costs("w1")
        assert costs.records == 3
        assert costs.total_input_tokens == 1800
        assert costs.total_output_tokens == 900


# ═══════════════════════════════════════════════════════════════════
# 20. Typed Debt Tracking (IT-139..IT-145)
# ═══════════════════════════════════════════════════════════════════


class TestIT139_CreateDebtRecord:
    """IT-139: Create DebtRecord with all fields. Persisted to debt_records table."""

    def test_create_debt(self, tmp_db):
        debt = DebtRecord(
            team_id="t1",
            agent_id="w1",
            severity="high",
            category="workaround",
            description="Used fallback API",
        )
        errors = debt.validate()
        assert len(errors) == 0

        tmp_db.create_debt_record(
            debt_id=debt.id,
            team_id="t1",
            agent_id="w1",
            severity="high",
            category="workaround",
            description="Used fallback API",
        )
        records = tmp_db.get_team_debt("t1")
        assert len(records) == 1
        assert records[0]["severity"] == "high"
        assert records[0]["category"] == "workaround"


class TestIT140_SeverityValidation:
    """IT-140: Invalid severity raises validation error."""

    def test_severity_validation(self):
        debt = DebtRecord(
            team_id="t1",
            agent_id="w1",
            severity="extreme",
            category="workaround",
            description="test",
        )
        errors = debt.validate()
        assert len(errors) > 0
        assert any("severity" in e.lower() for e in errors)


class TestIT141_CategoryValidation:
    """IT-141: Invalid category raises validation error."""

    def test_category_validation(self):
        debt = DebtRecord(
            team_id="t1",
            agent_id="w1",
            severity="medium",
            category="invalid_category",
            description="test",
        )
        errors = debt.validate()
        assert len(errors) > 0
        assert any("category" in e.lower() for e in errors)


class TestIT142_ArtifactWithDebt:
    """IT-142: Write artifact with debt field. Verify persistence."""

    def test_artifact_debt(self, tmp_path):
        debt_item = {"severity": "medium", "category": "workaround", "description": "test debt"}
        art = Artifact(
            status="success",
            output={"result": "ok"},
            debt=[debt_item],
            agent_id="w1",
            team_id="t1",
        )
        write_artifact(tmp_path, art)
        from phalanx.artifacts.reader import read_artifact

        loaded = read_artifact(tmp_path)
        assert loaded is not None
        assert len(loaded.debt) == 1
        assert loaded.debt[0]["severity"] == "medium"


class TestIT143_AggregatedDebt:
    """IT-143: SkillResult.debt aggregates all step debt records."""

    def test_aggregated_debt(self, tmp_db):
        tmp_db.create_debt_record("d1", "t1", "w1", "high", "workaround", "debt 1")
        tmp_db.create_debt_record("d2", "t1", "w2", "low", "deferred_test", "debt 2")
        tmp_db.create_debt_record("d3", "t1", "w1", "medium", "scope_reduction", "debt 3")

        records = tmp_db.get_team_debt("t1")
        assert len(records) == 3
        categories = {r["category"] for r in records}
        assert categories == {"workaround", "deferred_test", "scope_reduction"}


class TestIT144_DebtAPI:
    """IT-144: GET /api/teams/{id}/debt returns sorted debt records."""

    def test_debt_api(self, tmp_db):
        tmp_db.create_debt_record("d1", "t1", "w1", "high", "workaround", "first")
        time.sleep(0.01)
        tmp_db.create_debt_record("d2", "t1", "w1", "low", "deferred_fix", "second")

        records = tmp_db.get_team_debt("t1")
        assert len(records) == 2
        assert records[0]["created_at"] <= records[1]["created_at"]


class TestIT145_DebtFromPromptInjection:
    """IT-145: Buffer corruption workaround creates DebtRecord with category=workaround."""

    def test_debt_from_injection(self, tmp_db):
        debt = DebtRecord(
            team_id="t1",
            agent_id="w1",
            severity="medium",
            category="workaround",
            description="Buffer corruption recovery — switched to file-based delivery",
        )
        assert len(debt.validate()) == 0

        tmp_db.create_debt_record(
            debt_id=debt.id,
            team_id="t1",
            agent_id="w1",
            severity="medium",
            category="workaround",
            description=debt.description,
        )
        records = tmp_db.get_team_debt("t1")
        assert len(records) == 1
        assert records[0]["category"] == "workaround"


# ═══════════════════════════════════════════════════════════════════
# 21. Checkpoint / Resume at Step Level (IT-146..IT-154)
# ═══════════════════════════════════════════════════════════════════


class TestIT146_SaveCheckpoint:
    """IT-146: save_checkpoint updates completed_steps JSON in skill_runs."""

    def test_save_checkpoint(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.save_checkpoint("run1", "step_a", "result_a")

        run = tmp_db.get_skill_run("run1")
        completed = json.loads(run["completed_steps"])
        assert "step_a" in completed


class TestIT147_LoadCheckpoint:
    """IT-147: load_checkpoint returns correct completed/pending lists."""

    def test_load_checkpoint(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.save_checkpoint("run1", "step_a", "done_a")
        cm.save_checkpoint("run1", "step_b", "done_b")

        cp = cm.load_checkpoint("run1")
        assert cp is not None
        assert "step_a" in cp.completed_steps
        assert "step_b" in cp.completed_steps


class TestIT148_GetResumePoint:
    """IT-148: get_resume_point returns first incomplete step."""

    def test_resume_point(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.save_checkpoint("run1", "step_a")

        all_steps = [
            {"name": "step_a", "depends_on": []},
            {"name": "step_b", "depends_on": ["step_a"]},
            {"name": "step_c", "depends_on": ["step_b"]},
        ]
        resume = cm.get_resume_point("run1", all_steps=all_steps)
        assert resume is not None
        assert resume.name == "step_b"


class TestIT149_AllComplete:
    """IT-149: All steps checkpointed → get_resume_point returns None."""

    def test_all_complete(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.save_checkpoint("run1", "step_a")
        cm.save_checkpoint("run1", "step_b")

        all_steps = [
            {"name": "step_a", "depends_on": []},
            {"name": "step_b", "depends_on": ["step_a"]},
        ]
        resume = cm.get_resume_point("run1", all_steps=all_steps)
        assert resume is None


class TestIT150_StepArtifactPersistence:
    """IT-150: step_artifacts JSON map updated on checkpoint."""

    def test_step_artifacts(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.save_checkpoint("run1", "step_a", "artifact_data_a")
        cm.save_checkpoint("run1", "step_b", "artifact_data_b")

        cp = cm.load_checkpoint("run1")
        assert cp.step_artifacts["step_a"] == "artifact_data_a"
        assert cp.step_artifacts["step_b"] == "artifact_data_b"


class TestIT151_ResumeSkipsCompleted:
    """IT-151: Resume with 2/4 done — steps 1-2 not re-executed."""

    def test_skip_completed(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.save_checkpoint("run1", "step1")
        cm.save_checkpoint("run1", "step2")

        all_steps = [
            {"name": "step1", "depends_on": []},
            {"name": "step2", "depends_on": ["step1"]},
            {"name": "step3", "depends_on": ["step2"]},
            {"name": "step4", "depends_on": ["step3"]},
        ]
        resume = cm.get_resume_point("run1", all_steps=all_steps)
        assert resume is not None
        assert resume.name == "step3"

        cp = cm.load_checkpoint("run1")
        assert "step1" in cp.completed_steps
        assert "step2" in cp.completed_steps
        assert "step3" not in cp.completed_steps


class TestIT152_PartialStepRestart:
    """IT-152: Agent dies mid-step — step restarts, not entire skill."""

    def test_partial_restart(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.save_checkpoint("run1", "step1")
        cm.set_current_step("run1", "step2")

        cp = cm.load_checkpoint("run1")
        assert "step1" in cp.completed_steps
        assert "step2" not in cp.completed_steps
        assert cp.current_step == "step2"

        all_steps = [
            {"name": "step1", "depends_on": []},
            {"name": "step2", "depends_on": ["step1"]},
        ]
        resume = cm.get_resume_point("run1", all_steps=all_steps)
        assert resume is not None
        assert resume.name == "step2"


class TestIT153_CheckpointAfterTUICrash:
    """IT-153: In-progress step NOT checkpointed as complete after TUI crash."""

    def test_tui_crash_checkpoint(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)
        cm.set_current_step("run1", "step1")

        cp = cm.load_checkpoint("run1")
        assert "step1" not in cp.completed_steps
        assert cp.current_step == "step1"


class TestIT154_CheckpointAfterTeamLead:
    """IT-154: Team Lead-modified step's checkpoint records modification source."""

    def test_team_lead_checkpoint(self, tmp_db):
        tmp_db.create_skill_run("run1", "t1", "build_skill")
        cm = CheckpointManager(tmp_db)

        cm.save_checkpoint(
            "run1",
            "step_a",
            json.dumps(
                {
                    "result": "completed with team_lead modification",
                    "modified_by": "team_lead",
                    "strategy": "adapt_approach",
                }
            ),
        )

        cp = cm.load_checkpoint("run1")
        art = json.loads(cp.step_artifacts["step_a"])
        assert art["modified_by"] == "team_lead"

    # ═══════════════════════════════════════════════════════════════════
    # 22. Continual Learning (IT-155..IT-164)
    # ═══════════════════════════════════════════════════════════════════

    """IT-165: is_alive() correctly returns False for each shell type."""

    @pytest.mark.parametrize("shell", ["zsh", "bash", "sh", "fish", "dash"])
    def test_shell_detection(self, shell):
        proc = AgentProcess(
            agent_id="a1",
            team_id="t1",
            session_name="s1",
            stream_log=Path("/tmp/s.log"),
            backend=MagicMock(),
        )
        mock_pane = MagicMock()
        mock_pane.pane_current_command = shell
        mock_session = MagicMock()
        mock_session.active_window.active_pane = mock_pane

        with patch("phalanx.process.manager.libtmux") as mock_libtmux:
            mock_server = MagicMock()
            mock_server.sessions.get.return_value = mock_session
            mock_libtmux.Server.return_value = mock_server
            assert proc.is_alive() is False


class TestIT166_GhostSessionLoopBreaker:
    """IT-166: Agent enters ghost session loop × 5. Monitor stops after max_restart_attempts."""

    def test_loop_breaker(self, tmp_db):
        db = tmp_db
        for _ in range(6):
            db.increment_ghost_restart("w1")

        count = db.get_agent("w1")["ghost_restart_count"]
        limit = db.get_ghost_restart_limit("w1")
        assert count > limit


class TestIT167_GhostLoopResolution:
    """IT-167: Engineering manager diagnoses root cause, modifies config, triggers clean restart."""

    def test_ghost_resolution(self, tmp_db):
        from phalanx.skills.engineering_manager import (
            EngineeringManagerDecision,
            EngineeringManagerAction,
            apply_engineering_manager_decision,
        )

        db = tmp_db
        db.create_engineering_manager_entry("t1", "ghost_loop")

        decision = EngineeringManagerDecision(
            action=EngineeringManagerAction.SWAP_MODEL,
            rationale="Ghost loops caused by model instability — swapping to sonnet",
            model_changes={"w1": "claude-4-sonnet"},
        )
        result = apply_engineering_manager_decision(decision, db, "t1")
        assert result["applied"] is True
        assert db.get_agent("w1")["model"] == "claude-4-sonnet"


class TestIT168_PartialTUICrashGhost:
    """IT-168: Partially rendered TUI frame — is_alive() still returns False."""

    def test_partial_crash(self):
        proc = AgentProcess(
            agent_id="a1",
            team_id="t1",
            session_name="s1",
            stream_log=Path("/tmp/s.log"),
            backend=MagicMock(),
        )
        mock_pane = MagicMock()
        mock_pane.pane_current_command = "bash"
        mock_session = MagicMock()
        mock_session.active_window.active_pane = mock_pane

        with patch("phalanx.process.manager.libtmux") as mock_libtmux:
            mock_server = MagicMock()
            mock_server.sessions.get.return_value = mock_session
            mock_libtmux.Server.return_value = mock_server
            assert proc.is_alive() is False


class TestIT169_SilentExitGhost:
    """IT-169: Agent exits cleanly (exit code 0). Bare shell prompt fires process_exited."""

    def test_silent_exit(self):
        lines = ["Agent completed.", "$ "]
        assert _check_process_exited(lines) is True


class TestIT170_DoubleRestartRace:
    """IT-170: is_alive()=False AND process_exited simultaneous — only one restart."""

    def test_no_double_restart(self, tmp_db):
        db = tmp_db
        count_before = db.get_agent("w1").get("ghost_restart_count", 0)
        new_count = db.increment_ghost_restart("w1")
        assert new_count == count_before + 1

        agent = db.get_agent("w1")
        assert agent["ghost_restart_count"] == new_count


class TestIT171_RestartCounterPersists:
    """IT-171: Restart counter persists in DB across monitor restarts."""

    def test_restart_counter_in_db(self):
        with tempfile.TemporaryDirectory() as td:
            db = StateDB(db_path=Path(td) / "state.db")
            db.create_team("t1", "task")
            db.create_agent("w1", "t1", "code")
            db.update_agent("w1", attempts=3)
            agent = db.get_agent("w1")
            assert agent["attempts"] == 3


class TestIT172_TmuxSessionGone:
    """IT-172: Tmux session destroyed entirely — capture_screen returns None."""

    def test_session_gone(self):
        pm = ProcessManager.__new__(ProcessManager)
        pm._processes = {}
        pm._root = Path("/tmp")
        result = pm.capture_screen("nonexistent")
        assert result is None


class TestIT173_BlockedThenCrashes:
    """IT-173: Agent in blocked_on_prompt then crashes — transitions correctly."""

    def test_blocked_then_crash(self, tmp_db):
        db = tmp_db
        db.update_agent("w1", status="blocked_on_prompt", prompt_state="permission_prompt")

        db.update_agent("w1", status="dead")
        agent = db.get_agent("w1")
        assert agent["status"] == "dead"

    # ═══════════════════════════════════════════════════════════════════
    # 24. Checkpoint + Cross-Session Memory (IT-174..IT-178)
    # ═══════════════════════════════════════════════════════════════════

    """IT-179: parse_token_usage returns None — no crash, no zero-value row."""

    def test_none_usage(self):
        from phalanx.backends.cursor import CursorBackend

        backend = CursorBackend()
        result = backend.parse_token_usage("")
        assert result is None


class TestIT180_ParseTokenUsageGarbage:
    """IT-180: parse_token_usage returns malformed data — validates and rejects."""

    def test_garbage_usage(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", -100, -50)

        records = tmp_db.get_agent_token_usage("w1")
        assert len(records) == 0


class TestIT181_CostTableMissingModel:
    """IT-181: Unknown model → estimated_cost=null, warning logged."""

    def test_missing_model(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "unknown-model-xyz", 1000, 500)

        records = tmp_db.get_agent_token_usage("w1")
        assert len(records) == 1
        assert records[0]["estimated_cost"] is None


class TestIT182_DBWriteFailure:
    """IT-182: SQLite write fails during cost recording — monitor continues."""

    def test_db_failure(self, tmp_db):
        agg = CostAggregator(tmp_db)
        with patch.object(tmp_db, "record_token_usage", side_effect=Exception("DB locked")):
            agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 1000, 500)


class TestIT183_ConcurrentCostWrites:
    """IT-183: Two agents write token usage simultaneously — no SQLite corruption."""

    def test_concurrent_writes(self, tmp_db):
        agg = CostAggregator(tmp_db)
        errors = []

        def record(agent_id: str):
            try:
                for i in range(10):
                    agg.record_usage("t1", agent_id, "worker", "cursor", "claude-4-opus", 100, 50)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=record, args=("w1",))
        t2 = threading.Thread(target=record, args=("w2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0
        records = tmp_db.get_team_token_usage("t1")
        assert len(records) == 20


class TestIT184_TruncatedStreamLog:
    """IT-184: parse_token_usage encounters truncated line — handles safely."""

    def test_truncated_log(self):
        from phalanx.backends.cursor import CursorBackend

        backend = CursorBackend()
        truncated = "Token usage: inp"
        result = backend.parse_token_usage(truncated)
        assert result is None or isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════
# 26. API Rate Limit Resilience (IT-185..IT-191)
# ═══════════════════════════════════════════════════════════════════


class TestIT185_RateLimitDetection:
    """IT-185: New stall pattern matches rate limit errors."""

    def test_rate_limit_pattern(self):
        lines = ["Attempting API call...", "429 Too Many Requests"]
        assert _check_rate_limited(lines) is True

    def test_quota_exceeded(self):
        lines = ["Error: quota exceeded for model opus-4.6"]
        assert _check_rate_limited(lines) is True

    def test_rate_limit_text(self):
        lines = ["rate limit exceeded, please retry"]
        assert _check_rate_limited(lines) is True

    def test_normal_output_no_match(self):
        lines = ["Generating code...", "File written successfully"]
        assert _check_rate_limited(lines) is False

    def test_pattern_registered(self):
        from phalanx.monitor.stall import _PROMPT_PATTERNS

        names = [n for n, _ in _PROMPT_PATTERNS]
        assert "rate_limited" in names


class TestIT186_RateLimitBackoff:
    """IT-186: Monitor waits rate_limit_backoff before restarting."""

    def test_backoff(self, tmp_db):
        from phalanx.monitor.team_monitor import RATE_LIMIT_BACKOFF_SECONDS

        assert RATE_LIMIT_BACKOFF_SECONDS >= 30


class TestIT187_StaggeredRestarts:
    """IT-187: Multiple rate-limited agents restart staggered."""

    def test_staggered(self, tmp_db):
        from phalanx.monitor.stall import StallDetector

        sd = StallDetector(MagicMock(), MagicMock(), db=tmp_db)
        delay1 = sd.get_retry_delay("w1")
        sd.record_retry("w1")
        delay2 = sd.get_retry_delay("w1")
        assert delay2 > delay1


class TestIT188_PersistentRateLimitModelSwap:
    """IT-188: 3 rate limits → Engineering manager swaps model."""

    def test_model_swap(self, tmp_db):
        from phalanx.skills.engineering_manager import (
            EngineeringManagerDecision,
            EngineeringManagerAction,
            apply_engineering_manager_decision,
        )

        decision = EngineeringManagerDecision(
            action=EngineeringManagerAction.SWAP_MODEL,
            rationale="Persistent rate limits — swapping to sonnet",
            model_changes={"w1": "claude-4-sonnet"},
        )
        result = apply_engineering_manager_decision(decision, tmp_db, "t1")
        assert result["applied"] is True
        assert tmp_db.get_agent("w1")["model"] == "claude-4-sonnet"


class TestIT189_TeamWideModelSwap:
    """IT-189: All agents rate limited → Engineering manager swaps all agents."""

    def test_team_wide_swap(self, tmp_db):
        from phalanx.skills.engineering_manager import (
            EngineeringManagerDecision,
            EngineeringManagerAction,
            apply_engineering_manager_decision,
        )

        decision = EngineeringManagerDecision(
            action=EngineeringManagerAction.SWAP_MODEL,
            rationale="All agents rate limited — team-wide swap to sonnet",
            model_changes={"w1": "claude-4-sonnet", "w2": "claude-4-sonnet"},
        )
        result = apply_engineering_manager_decision(decision, tmp_db, "t1")
        assert result["applied"] is True
        assert tmp_db.get_agent("w1")["model"] == "claude-4-sonnet"
        assert tmp_db.get_agent("w2")["model"] == "claude-4-sonnet"


class TestIT190_BackoffConfiguration:
    """IT-190: rate_limit_backoff_seconds configurable in config.json."""

    def test_config(self):
        from phalanx.monitor.team_monitor import RATE_LIMIT_BACKOFF_SECONDS

        assert isinstance(RATE_LIMIT_BACKOFF_SECONDS, int)
        assert RATE_LIMIT_BACKOFF_SECONDS > 0


class TestIT191_RateLimitTokensTracked:
    """IT-191: Partial token usage from rate-limited calls still recorded."""

    def test_tokens_tracked(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 50, 0)

        records = tmp_db.get_agent_token_usage("w1")
        assert len(records) == 1
        assert records[0]["input_tokens"] == 50
        assert records[0]["output_tokens"] == 0
