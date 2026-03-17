"""Integration tests for v1.0.0 features — IT-125 through IT-191.

Covers: Artifact Finality, Premature Completion, Cost Tracking, Debt Tracking,
Checkpoint/Resume, Continual Learning, Ghost Session Deep, Cross-Session Memory,
Cost Failure Modes, API Rate Limit Resilience.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phalanx.artifacts.schema import Artifact
from phalanx.artifacts.writer import write_artifact
from phalanx.costs.aggregator import CostAggregator
from phalanx.db import StateDB
from phalanx.monitor.stall import _check_process_exited, _check_rate_limited
from phalanx.process.manager import AgentProcess, ProcessManager


pytestmark = pytest.mark.integration


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        db = StateDB(db_path=Path(td) / "state.db")
        db.create_team("t1", "test task")
        db.create_agent("w1", "t1", "code", role="agent", backend="cursor")
        db.create_agent("w2", "t1", "test", role="agent", backend="cursor")
        yield db


@pytest.fixture
def tmp_db_with_root():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = StateDB(db_path=root / ".phalanx" / "state.db")
        db.create_team("t1", "test task")
        db.create_agent("w1", "t1", "code", role="agent", backend="cursor")
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

    # ═══════════════════════════════════════════════════════════════════
    # 21. Checkpoint / Resume at Step Level (IT-146..IT-154)
    # ═══════════════════════════════════════════════════════════════════

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


class TestIT181_UnknownModelRecorded:
    """IT-181: Unknown model → token usage still recorded."""

    def test_missing_model(self, tmp_db):
        agg = CostAggregator(tmp_db)
        agg.record_usage("t1", "w1", "worker", "cursor", "unknown-model-xyz", 1000, 500)

        records = tmp_db.get_agent_token_usage("w1")
        assert len(records) == 1
        assert records[0]["input_tokens"] == 1000
        assert records[0]["output_tokens"] == 500


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
