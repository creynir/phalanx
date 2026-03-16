"""Tests for the SQLite database layer."""

from __future__ import annotations

import time

import pytest

from phalanx.db import StateDB


@pytest.fixture
def db(tmp_path):
    d = StateDB(db_path=tmp_path / "test.db")
    yield d


class TestTeams:
    def test_create_and_get(self, db):
        db.create_team("t1", "fix tests")
        team = db.get_team("t1")
        assert team["id"] == "t1"
        assert team["task"] == "fix tests"
        assert team["status"] == "running"

    def test_get_missing(self, db):
        assert db.get_team("nonexistent") is None

    def test_list_teams(self, db):
        db.create_team("t1", "task1")
        db.create_team("t2", "task2")
        teams = db.list_teams()
        assert len(teams) == 2
        ids = [t["id"] for t in teams]
        assert "t1" in ids
        assert "t2" in ids

    def test_update_team_status(self, db):
        db.create_team("t1", "task1")
        db.update_team_status("t1", status="dead")
        team = db.get_team("t1")
        assert team["status"] == "dead"

    def test_delete_team_cascades(self, db):
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", "sub-task", "agent", "cursor")
        db.post_to_feed("t1", "a1", "hello")
        db.delete_team("t1")
        assert db.get_team("t1") is None
        assert db.get_agent("a1") is None


class TestAgents:
    def test_create_and_get(self, db):
        db.create_team("t1", "task1")
        db.create_agent(
            "a1", "t1", task="sub-task", role="agent", backend="cursor", model="sonnet"
        )
        agent = db.get_agent("a1")
        assert agent["id"] == "a1"
        assert agent["team_id"] == "t1"
        assert agent["role"] == "agent"
        assert agent["task"] == "sub-task"
        assert agent["backend"] == "cursor"
        assert agent["model"] == "sonnet"
        assert agent["status"] == "pending"

    def test_list_agents_by_team(self, db):
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", "task1")
        db.create_team("t2", "task2")
        db.create_agent("a2", "t2", "task2")
        agents = db.list_agents("t1")
        assert len(agents) == 1
        assert agents[0]["id"] == "a1"

    def test_update_agent(self, db):
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", "task1")
        db.update_agent("a1", status="running", attempts=3)
        agent = db.get_agent("a1")
        assert agent["status"] == "running"
        assert agent["attempts"] == 3


class TestFeed:
    def test_post_and_get(self, db):
        db.create_team("t1", "task1")
        msg_id = db.post_to_feed("t1", "agent-1", "found a bug in auth")
        assert msg_id > 0
        msgs = db.get_feed("t1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "found a bug in auth"
        assert msgs[0]["sender_id"] == "agent-1"

    def test_feed_ordering(self, db):
        db.create_team("t1", "task1")
        db.post_to_feed("t1", "a1", "first")
        db.post_to_feed("t1", "a2", "second")
        msgs = db.get_feed("t1")
        assert len(msgs) == 2
        assert msgs[0]["content"] == "first"
        assert msgs[1]["content"] == "second"

    def test_feed_limit(self, db):
        db.create_team("t1", "task1")
        for i in range(10):
            db.post_to_feed("t1", "a1", f"msg-{i}")
        msgs = db.get_feed("t1", limit=3)
        assert len(msgs) == 3

    def test_feed_since(self, db):
        import time as _time

        db.create_team("t1", "task1")
        db.post_to_feed("t1", "a1", "old message")
        cutoff = _time.time()
        _time.sleep(0.01)
        db.post_to_feed("t1", "a1", "new message")
        msgs = db.get_feed("t1", since=cutoff)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "new message"


class TestFileLocks:
    def test_acquire_and_release(self, db):
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", "task1")
        assert db.acquire_lock("/src/foo.py", "t1", "a1", 1234) is True

        # Second acquire fails
        assert db.acquire_lock("/src/foo.py", "t1", "a1", 1234) is False

        db.release_lock("/src/foo.py")
        assert db.acquire_lock("/src/foo.py", "t1", "a1", 1234) is True

    def test_release_agent_locks(self, db):
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", "task1")
        db.acquire_lock("/a.py", "t1", "a1", 1234)
        db.acquire_lock("/b.py", "t1", "a1", 1234)
        count = db.release_agent_locks("a1")
        assert count == 2


class TestMigration:
    def test_migrate_from_v2_messages_to_feed(self, tmp_path):
        """Simulate an old v2 database with messages table."""
        import sqlite3

        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE teams (
                id TEXT PRIMARY KEY, task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                created_at REAL NOT NULL, updated_at REAL NOT NULL, config TEXT
            );
            CREATE TABLE agents (
                id TEXT PRIMARY KEY, team_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'worker', task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', pid INTEGER,
                chat_id TEXT, worktree TEXT, model TEXT,
                backend TEXT DEFAULT 'cursor',
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                artifact_status TEXT, last_heartbeat REAL,
                attempts INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3,
                stall_seconds INTEGER DEFAULT 1800, max_runtime INTEGER DEFAULT 1800,
                prompt_state TEXT, prompt_screen TEXT
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT NOT NULL, agent_id TEXT, sender TEXT NOT NULL,
                content TEXT NOT NULL, created_at REAL NOT NULL,
                delivered INTEGER DEFAULT 0
            );
            CREATE TABLE file_locks (
                file_path TEXT PRIMARY KEY, team_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, pid INTEGER NOT NULL, locked_at REAL NOT NULL
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT NOT NULL, agent_id TEXT,
                event_type TEXT NOT NULL, payload TEXT, created_at REAL NOT NULL
            );
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (2);
            INSERT INTO teams VALUES ('t1', 'task', 'running', 1.0, 1.0, NULL);
            INSERT INTO messages VALUES (1, 't1', NULL, 'user', 'hello', 1.0, 0);
        """)
        conn.close()

        db = StateDB(db_path=db_path)

        feed = db.get_feed("t1")
        assert len(feed) == 1
        assert feed[0]["content"] == "hello"
        assert feed[0]["sender_id"] == "user"

        db.post_to_feed("t1", "agent-1", "world")
        feed = db.get_feed("t1")
        assert len(feed) == 2


class TestAgentV2Schema:
    """v2 schema changes: soul_path column and role constraint."""

    def test_soul_path_column_exists(self, db):
        """soul_path column must exist on the agents table."""
        import sqlite3

        conn = sqlite3.connect(str(db._path))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
        conn.close()
        assert "soul_path" in cols

    def test_create_agent_accepts_soul_path(self, db):
        """create_agent() must accept a soul_path keyword argument."""
        db.create_team("t1", "task1")
        # Should not raise
        db.create_agent(
            "a1", "t1", task="sub-task", role="lead", backend="cursor",
            soul_path="/souls/lead.md",
        )
        agent = db.get_agent("a1")
        assert agent["soul_path"] == "/souls/lead.md"

    def test_get_agent_returns_soul_path(self, db):
        """get_agent() result dict must contain soul_path key."""
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", task="sub-task", role="agent", backend="cursor")
        agent = db.get_agent("a1")
        assert "soul_path" in agent

    def test_soul_path_defaults_to_none(self, db):
        """soul_path should be None when not provided at creation."""
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", task="sub-task", role="agent", backend="cursor")
        agent = db.get_agent("a1")
        assert agent["soul_path"] is None

    def test_update_agent_soul_path(self, db):
        """update_agent() must be able to update soul_path."""
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", task="sub-task", role="agent", backend="cursor")
        db.update_agent("a1", soul_path="/souls/updated.md")
        agent = db.get_agent("a1")
        assert agent["soul_path"] == "/souls/updated.md"

    def test_role_lead_is_valid(self, db):
        """role='lead' must be accepted and soul_path must be present in the result."""
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", task="lead-task", role="lead", backend="cursor",
                        soul_path="/souls/lead.md")
        agent = db.get_agent("a1")
        assert agent["role"] == "lead"
        # soul_path key existence confirms v2 schema is in place
        assert "soul_path" in agent

    def test_role_agent_is_valid(self, db):
        """role='agent' must be accepted and soul_path must be present in the result."""
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", task="agent-task", role="agent", backend="cursor",
                        soul_path="/souls/agent.md")
        agent = db.get_agent("a1")
        assert agent["role"] == "agent"
        # soul_path key existence confirms v2 schema is in place
        assert "soul_path" in agent

    def test_role_invalid_value_raises(self, db):
        """role values other than 'lead' or 'agent' must raise an error."""
        import sqlite3

        db.create_team("t1", "task1")
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            db.create_agent("a1", "t1", task="task", role="coder", backend="cursor")

    def test_role_invalid_reviewer_raises(self, db):
        """role='reviewer' (another v1 value) must be rejected."""
        import sqlite3

        db.create_team("t1", "task1")
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            db.create_agent("a1", "t1", task="task", role="reviewer", backend="cursor")

    def test_role_invalid_on_update_raises(self, db):
        """update_agent() with an invalid role must raise an error."""
        import sqlite3

        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", task="task", role="lead", backend="cursor")
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            db.update_agent("a1", role="architect")


class TestTransaction:
    def test_rollback_on_error(self, db):
        db.create_team("t1", "task1")
        try:
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO teams (id, task, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("t2", "task2", "running", time.time(), time.time()),
                )
                raise ValueError("Oops")
        except ValueError:
            pass

        assert db.get_team("t2") is None
