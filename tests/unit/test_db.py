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
        db.create_agent("a1", "t1", "sub-task", "worker", "cursor")
        db.send_message("t1", "user", "hello")
        db.delete_team("t1")
        assert db.get_team("t1") is None
        assert db.get_agent("a1") is None


class TestAgents:
    def test_create_and_get(self, db):
        db.create_team("t1", "task1")
        db.create_agent(
            "a1", "t1", task="sub-task", role="worker", backend="cursor", model="sonnet"
        )
        agent = db.get_agent("a1")
        assert agent["id"] == "a1"
        assert agent["team_id"] == "t1"
        assert agent["role"] == "worker"
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


class TestMessages:
    def test_insert_and_get(self, db):
        db.create_team("t1", "task1")
        db.create_agent("a1", "t1", "task1")
        msg_id = db.send_message("t1", "user", "do this", agent_id="a1")
        assert msg_id > 0
        msgs = db.get_pending_messages("a1")
        assert len(msgs) == 1
        assert msgs[0]["id"] == msg_id
        assert msgs[0]["content"] == "do this"


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
