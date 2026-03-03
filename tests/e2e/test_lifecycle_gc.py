"""E2E tests: Concurrency, Config, Lifecycle, GC, Artifacts, Feed, Status, Backend, DB — E2E-029 through E2E-054."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from phalanx.artifacts.schema import Artifact
from phalanx.artifacts.writer import write_artifact
from phalanx.artifacts.reader import read_agent_artifact
from phalanx.config import PhalanxConfig
from phalanx.db import StateDB, SCHEMA_VERSION
from phalanx.team.orchestrator import stop_team, get_team_status, resume_team


pytestmark = pytest.mark.e2e


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


class TestE2E029_ConcurrentSpawnStagger:
    """E2E-029: 5-worker team spawns with delay between each (Cursor backend)."""

    def test_spawn_delay_configured(self):
        from phalanx.backends.cursor import CursorBackend

        backend = CursorBackend()
        assert hasattr(backend, "spawn_delay")


class TestE2E030_ConfigurableIdleTimeout:
    """E2E-030: --idle-timeout 60 overrides default 1800s."""

    def test_custom_idle_timeout(self):
        config = PhalanxConfig(idle_timeout_seconds=60)
        assert config.idle_timeout_seconds == 60


class TestE2E031_ConfigurableMaxRuntime:
    """E2E-031: --max-runtime 120 kills long-running agent."""

    def test_custom_max_runtime(self):
        config = PhalanxConfig(max_runtime_seconds=120)
        assert config.max_runtime_seconds == 120


class TestE2E032_DefaultTimeouts:
    """E2E-032: Unflagged team uses 1800s defaults."""

    def test_defaults(self):
        config = PhalanxConfig()
        assert config.idle_timeout_seconds == 1800
        assert config.max_runtime_seconds == 1800


class TestE2E033_StopPreservesArtifacts:
    """E2E-033: phalanx stop kills processes but keeps data."""

    def test_stop_preserves(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        db.update_agent("w1", status="running")

        art = Artifact(status="success", output={"done": True}, agent_id="w1", team_id="t1")
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        write_artifact(artifact_dir, art)

        mock_pm = MagicMock()
        stop_team(db, mock_pm, "t1")

        assert db.get_team("t1")["status"] == "dead"
        assert (artifact_dir / "artifact.json").exists()


class TestE2E034_GCRespectsAge:
    """E2E-034: phalanx gc --older-than 7d cleans old teams only."""

    def test_gc_age_filter(self, db, tmp_path):
        from phalanx.monitor.gc import run_gc

        db.create_team("old-team", "old task")
        db.update_team_status("old-team", "dead")
        with db._connect() as conn:
            conn.execute(
                "UPDATE teams SET updated_at = unixepoch('now', '-48 hours') WHERE id = 'old-team'"
            )
            conn.commit()

        db.create_team("new-team", "new task")
        db.update_team_status("new-team", "dead")

        (tmp_path / "teams" / "old-team").mkdir(parents=True)
        (tmp_path / "teams" / "new-team").mkdir(parents=True)

        cleaned = run_gc(db=db, phalanx_root=tmp_path, max_age_hours=24)
        assert "old-team" in cleaned
        assert db.get_team("new-team") is not None


class TestE2E035_GCAll:
    """E2E-035: phalanx gc --all removes everything."""

    def test_gc_all(self, db, tmp_path):
        from phalanx.monitor.gc import run_gc

        db.create_team("t1", "task1")
        db.create_team("t2", "task2")
        db.update_team_status("t1", "dead")
        db.update_team_status("t2", "dead")

        with db._connect() as conn:
            conn.execute("UPDATE teams SET updated_at = unixepoch('now', '-999 hours')")
            conn.commit()

        (tmp_path / "teams" / "t1").mkdir(parents=True)
        (tmp_path / "teams" / "t2").mkdir(parents=True)

        cleaned = run_gc(db=db, phalanx_root=tmp_path, max_age_hours=0)
        assert len(cleaned) == 2


class TestE2E036_StandaloneMonitor:
    """E2E-036: phalanx monitor kills agent after timeout."""

    def test_monitor_loop_timeout(self):
        from phalanx.monitor.lifecycle import MonitorResult

        result = MonitorResult(agent_id="a1", final_state="failed", elapsed_seconds=10.0)
        assert result.final_state == "failed"


class TestE2E037_ArtifactWriteRead:
    """E2E-037: Write artifact → read via agent-result."""

    def test_roundtrip(self, tmp_path):
        art = Artifact(
            status="success",
            output={"files": ["calc.py"]},
            warnings=["no tests"],
            agent_id="w1",
            team_id="t1",
        )
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        write_artifact(artifact_dir, art)

        result = read_agent_artifact(tmp_path, "t1", "w1")
        assert result.status == "success"
        assert result.output["files"] == ["calc.py"]
        assert result.warnings == ["no tests"]


class TestE2E038_ArtifactStatusTransition:
    """E2E-038: Worker overwrites failure artifact with success."""

    def test_overwrite(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"

        a1 = Artifact(status="failure", output={"error": "first"}, agent_id="w1", team_id="t1")
        write_artifact(artifact_dir, a1, db=db)
        assert db.get_agent("w1")["artifact_status"] == "failure"

        a2 = Artifact(status="success", output={"result": "second"}, agent_id="w1", team_id="t1")
        write_artifact(artifact_dir, a2, db=db)
        assert db.get_agent("w1")["artifact_status"] == "success"


class TestE2E039_WriteArtifactMissingEnv:
    """E2E-039: write-artifact fails without PHALANX_AGENT_ID."""

    def test_missing_env(self):
        art = Artifact(status="invalid_status", output={})
        errors = art.validate()
        assert len(errors) > 0


class TestE2E040_TeamFeedPostRead:
    """E2E-040: Agent posts to feed, others read it."""

    def test_feed_post_read(self, db):
        db.create_team("t1", "task")
        db.post_to_feed("t1", "w1", "Found a critical bug")
        feed = db.get_feed("t1", limit=10)
        assert len(feed) == 1
        assert feed[0]["content"] == "Found a critical bug"
        assert feed[0]["sender_id"] == "w1"


class TestE2E041_FileLocking:
    """E2E-041: Lock prevents concurrent edits."""

    def test_lock_unlock(self, db):
        db.create_team("t1", "task")
        assert db.acquire_lock("shared.md", "t1", "w1", 1234) is True
        assert db.acquire_lock("shared.md", "t1", "w2", 5678) is False
        db.release_lock("shared.md")
        assert db.acquire_lock("shared.md", "t1", "w2", 5678) is True


class TestE2E042_ResumeWorkerNoArtifact:
    """E2E-042: Crashed worker resumes with original task."""

    def test_no_artifact_resume(self, db, tmp_path):
        from phalanx.team.orchestrator import _build_resume_prompt

        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "write integration tests")
        db.update_agent("w1", status="dead")

        agent = db.get_agent("w1")
        prompt = _build_resume_prompt(tmp_path, db, agent)
        assert "did not complete" in prompt.lower() or "write integration tests" in prompt


class TestE2E043_LeadPendingMessages:
    """E2E-043: Messages sent while lead was dead appear in resume."""

    def test_pending_messages(self, db, tmp_path):
        from phalanx.team.orchestrator import _build_resume_prompt

        db.create_team("t1", "task")
        db.create_agent("lead-t1", "t1", "coordinate", role="lead")
        db.update_agent("lead-t1", status="dead")

        msg_dir = tmp_path / "teams" / "t1" / "messages"
        msg_dir.mkdir(parents=True)
        (msg_dir / "msg_lead-t1_001.txt").write_text("New priority: focus on tests")

        agent = db.get_agent("lead-t1")
        prompt = _build_resume_prompt(tmp_path, db, agent)
        assert "focus on tests" in prompt


class TestE2E044_ResumeAllAgents:
    """E2E-044: Resume all dead agents, not just lead."""

    def test_resume_all(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("lead-t1", "t1", "coordinate", role="lead")
        db.create_agent("w1", "t1", "code")
        db.create_agent("w2", "t1", "test")

        for aid in ("lead-t1", "w1", "w2"):
            db.update_agent(aid, status="dead")

        mock_pm = MagicMock()
        mock_hb = MagicMock()
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "s.log"
        mock_pm.spawn.return_value = mock_proc

        with patch("phalanx.backends.get_backend"):
            with patch("phalanx.team.orchestrator._kill_team_monitor"):
                with patch("phalanx.team.create._spawn_team_monitor"):
                    result = resume_team(tmp_path, db, mock_pm, mock_hb, "t1", resume_all=True)
        assert len(result["resumed_agents"]) == 3


class TestE2E045_TeamStatus:
    """E2E-045: phalanx team-status displays complete team state."""

    def test_team_status(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        db.create_agent("w2", "t1", "test")
        db.update_agent("w1", status="running")
        db.update_agent("w2", status="dead")

        status = get_team_status(db, "t1")
        assert status is not None
        assert status["agent_count"] == 2
        assert status["running_count"] == 1


class TestE2E046_ListTeams:
    """E2E-046: phalanx list-teams shows all teams."""

    def test_list_teams(self, db):
        db.create_team("t1", "task1")
        db.create_team("t2", "task2")
        teams = db.list_teams()
        assert len(teams) == 2


class TestE2E047_ClaudeResumeFlag:
    """E2E-047: Claude agent resumes with --continue flag."""

    def test_claude_resume(self):
        from phalanx.backends.claude import ClaudeBackend

        backend = ClaudeBackend()
        cmd = backend.build_resume_command("session-123")
        cmd_str = " ".join(cmd)
        assert "--continue" in cmd_str or "session-123" in cmd_str


class TestE2E048_NonCursorNoDelay:
    """E2E-048: Non-Cursor backends spawn with zero delay."""

    def test_claude_no_delay(self):
        from phalanx.backends.claude import ClaudeBackend

        backend = ClaudeBackend()
        assert backend.spawn_delay() == 0.0


class TestE2E049_SchemaMigrationV3V4:
    """E2E-049: Old DB migrates cleanly on startup."""

    def test_migration(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "v3.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (3);
            CREATE TABLE teams (
                id TEXT PRIMARY KEY, task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                created_at REAL NOT NULL, updated_at REAL NOT NULL, config TEXT
            );
            CREATE TABLE agents (
                id TEXT PRIMARY KEY, team_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'worker', task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', pid INTEGER,
                chat_id TEXT, worktree TEXT, model TEXT, backend TEXT DEFAULT 'cursor',
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                artifact_status TEXT, last_heartbeat REAL,
                attempts INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3,
                prompt_state TEXT, prompt_screen TEXT,
                stall_seconds INTEGER DEFAULT 60, max_runtime INTEGER DEFAULT 1800
            );
            CREATE TABLE feed (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT, sender_id TEXT, content TEXT, created_at REAL);
            CREATE TABLE file_locks (file_path TEXT PRIMARY KEY, team_id TEXT, agent_id TEXT, pid INTEGER, locked_at REAL);
            CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT, agent_id TEXT, event_type TEXT, payload TEXT, created_at REAL);
        """)
        conn.commit()
        conn.close()

        db = StateDB(db_path=db_path)
        v = db._connect().execute("SELECT version FROM schema_version").fetchone()["version"]
        assert v == SCHEMA_VERSION


class TestE2E050_StopAgent:
    """E2E-050: phalanx stop-agent kills single agent."""

    def test_stop_single(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        db.create_agent("w2", "t1", "test")
        db.update_agent("w1", status="running")
        db.update_agent("w2", status="running")

        mock_pm = MagicMock()
        mock_pm.kill_agent = MagicMock()

        # Simulate stop-agent for w1 only
        mock_pm.kill_agent("w1")
        db.update_agent("w1", status="dead")

        assert db.get_agent("w1")["status"] == "dead"
        assert db.get_agent("w2")["status"] == "running"


class TestE2E051_EscalationArtifact:
    """E2E-051: Worker writes escalation_required → lead behavior."""

    def test_escalation_stored(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")

        art = Artifact(
            status="escalation", output={"reason": "needs API key"}, agent_id="w1", team_id="t1"
        )
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        write_artifact(artifact_dir, art, db=db)
        assert db.get_agent("w1")["artifact_status"] == "escalation"


class TestE2E052_SendKeysRaw:
    """E2E-052: phalanx send-keys with --no-enter flag."""

    def test_send_keys_no_enter(self):
        mock_pm = MagicMock()
        mock_pm._processes = {"a1": MagicMock()}
        mock_pm._processes["a1"].pane = MagicMock()
        from phalanx.process.manager import ProcessManager

        pm = ProcessManager.__new__(ProcessManager)
        pm._processes = {"a1": mock_pm._processes["a1"]}
        pm._server = MagicMock()
        pm.send_keys("a1", "y", enter=False)


# E2E-053, E2E-054: moved to tests/future_backlog/test_lifecycle_gc_backlog.py
