"""Integration tests for Database Operations — IT-001 through IT-008."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from phalanx.db import StateDB, SCHEMA_VERSION


pytestmark = pytest.mark.integration


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


class TestIT001_CreateTeam:
    """IT-001: Verifies creating a team writes correct defaults to the teams table."""

    def test_creates_team_with_defaults(self, db):
        db.create_team("team-1", "build a calculator")
        team = db.get_team("team-1")
        assert team is not None
        assert team["id"] == "team-1"
        assert team["task"] == "build a calculator"
        assert team["status"] == "running"
        assert team["created_at"] > 0
        assert team["updated_at"] > 0

    def test_creates_team_with_config(self, db):
        config = {"model": "opus-4.6", "backend": "cursor"}
        db.create_team("team-2", "task", config=config)
        team = db.get_team("team-2")
        assert team["config"] is not None
        import json

        assert json.loads(team["config"]) == config


class TestIT002_CreateAgent:
    """IT-002: Verifies worker/lead creation initializes DB with status='pending'."""

    def test_creates_worker_with_pending_status(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "write code", role="worker")
        agent = db.get_agent("w1")
        assert agent is not None
        assert agent["status"] == "pending"
        assert agent["role"] == "worker"
        assert agent["team_id"] == "t1"

    def test_creates_lead_with_pending_status(self, db):
        db.create_team("t1", "task")
        db.create_agent("lead1", "t1", "coordinate", role="lead")
        agent = db.get_agent("lead1")
        assert agent["status"] == "pending"
        assert agent["role"] == "lead"


class TestIT003_ListAgents:
    """IT-003: Validates returned status lists for combinations of active/suspended/dead agents."""

    def test_mixed_statuses(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "task1")
        db.create_agent("w2", "t1", "task2")
        db.create_agent("w3", "t1", "task3")

        db.update_agent("w1", status="running")
        db.update_agent("w2", status="suspended")
        db.update_agent("w3", status="dead")

        agents = db.list_agents("t1")
        statuses = {a["id"]: a["status"] for a in agents}
        assert statuses["w1"] == "running"
        assert statuses["w2"] == "suspended"
        assert statuses["w3"] == "dead"


class TestIT004_ConcurrentAccess:
    """IT-004: Two processes attempting to create/update team data handle locks gracefully."""

    def test_concurrent_writes_no_corruption(self, tmp_path):
        db1 = StateDB(db_path=tmp_path / "shared.db")
        db2 = StateDB(db_path=tmp_path / "shared.db")

        db1.create_team("t1", "task")
        db1.create_agent("w1", "t1", "task1")

        errors = []

        def updater(db_inst, agent_id, n):
            try:
                for i in range(20):
                    db_inst.update_agent(agent_id, status=f"running-{n}-{i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=updater, args=(db1, "w1", 1))
        t2 = threading.Thread(target=updater, args=(db2, "w1", 2))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0
        agent = db1.get_agent("w1")
        assert agent is not None


class TestIT005_UpdateAgentArtifact:
    """IT-005: artifact_status and artifact_path correctly mutate in SQLite."""

    def test_artifact_status_update(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "task1")
        db.update_agent("w1", artifact_status="success")
        agent = db.get_agent("w1")
        assert agent["artifact_status"] == "success"

    def test_artifact_status_overwrite(self, db):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "task1")
        db.update_agent("w1", artifact_status="failure")
        db.update_agent("w1", artifact_status="success")
        agent = db.get_agent("w1")
        assert agent["artifact_status"] == "success"


class TestIT006_MigrationV3ToV4:
    """IT-006: DB upgrade drops stall_seconds and max_runtime columns."""

    def test_v3_to_v4_migration(self, tmp_path):
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
                id TEXT PRIMARY KEY, team_id TEXT NOT NULL REFERENCES teams(id),
                role TEXT NOT NULL DEFAULT 'worker', task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', pid INTEGER,
                chat_id TEXT, worktree TEXT, model TEXT, backend TEXT DEFAULT 'cursor',
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                artifact_status TEXT, last_heartbeat REAL,
                attempts INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3,
                prompt_state TEXT, prompt_screen TEXT,
                stall_seconds INTEGER DEFAULT 60, max_runtime INTEGER DEFAULT 1800
            );
            CREATE TABLE feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT NOT NULL,
                sender_id TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE file_locks (
                file_path TEXT PRIMARY KEY, team_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, pid INTEGER NOT NULL, locked_at REAL NOT NULL
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT NOT NULL,
                agent_id TEXT, event_type TEXT NOT NULL, payload TEXT, created_at REAL NOT NULL
            );
        """)
        conn.execute("INSERT INTO teams VALUES ('t1','task','running',1,1,NULL)")
        conn.execute(
            "INSERT INTO agents VALUES "
            "('w1','t1','worker','task','running',NULL,NULL,NULL,NULL,'cursor',1,1,NULL,NULL,0,3,NULL,NULL,60,1800)"
        )
        conn.commit()
        conn.close()

        db = StateDB(db_path=db_path)
        conn = db._connect()
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == SCHEMA_VERSION

        cols = [row[1] for row in conn.execute("PRAGMA table_info(agents)")]
        assert "stall_seconds" not in cols
        assert "max_runtime" not in cols

        agent = db.get_agent("w1")
        assert agent is not None
        assert agent["task"] == "task"
        conn.close()


# IT-007: moved to tests/future_backlog/test_integration_backlog.py


class TestIT008_SchemaVersionGuard:
    """IT-008: Running v1.0.0 code against v3 DB triggers migration chain."""

    def test_v3_triggers_migration(self, tmp_path):
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
                id TEXT PRIMARY KEY, team_id TEXT NOT NULL REFERENCES teams(id),
                role TEXT NOT NULL DEFAULT 'worker', task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', pid INTEGER,
                chat_id TEXT, worktree TEXT, model TEXT, backend TEXT DEFAULT 'cursor',
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                artifact_status TEXT, last_heartbeat REAL,
                attempts INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3,
                prompt_state TEXT, prompt_screen TEXT,
                stall_seconds INTEGER DEFAULT 60, max_runtime INTEGER DEFAULT 1800
            );
            CREATE TABLE feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT NOT NULL,
                sender_id TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE file_locks (
                file_path TEXT PRIMARY KEY, team_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, pid INTEGER NOT NULL, locked_at REAL NOT NULL
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT NOT NULL,
                agent_id TEXT, event_type TEXT NOT NULL, payload TEXT, created_at REAL NOT NULL
            );
        """)
        conn.execute("INSERT INTO teams VALUES ('t1','task','running',1,1,NULL)")
        conn.commit()
        conn.close()

        db = StateDB(db_path=db_path)
        team = db.get_team("t1")
        assert team is not None
        assert team["task"] == "task"
        v = db._connect().execute("SELECT version FROM schema_version").fetchone()["version"]
        assert v == SCHEMA_VERSION
