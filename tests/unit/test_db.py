"""Tests for phalanx.db module."""

from __future__ import annotations

import pytest

from phalanx.db import Database


@pytest.fixture
def db(tmp_path):
    d = Database(db_path=tmp_path / "test.db")
    yield d
    d.close()


class TestTeams:
    def test_create_and_get(self, db):
        db.create_team("t1", "fix tests", "cursor", model="sonnet-4.6")
        team = db.get_team("t1")
        assert team["id"] == "t1"
        assert team["task"] == "fix tests"
        assert team["backend"] == "cursor"
        assert team["model"] == "sonnet-4.6"
        assert team["status"] == "running"

    def test_get_missing(self, db):
        assert db.get_team("nonexistent") is None

    def test_list_teams(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_team("t2", "task2", "claude")
        assert len(db.list_teams()) == 2

    def test_list_teams_by_status(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_team("t2", "task2", "claude")
        db.update_team("t2", status="dead")
        assert len(db.list_teams(status="running")) == 1

    def test_update_team(self, db):
        db.create_team("t1", "task1", "cursor")
        db.update_team("t1", status="dead", model="opus")
        team = db.get_team("t1")
        assert team["status"] == "dead"
        assert team["model"] == "opus"

    def test_delete_team_cascades(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "sub-task", "cursor")
        db.insert_message("t1", "user", "hello", agent_id="a1")
        db.delete_team("t1")
        assert db.get_team("t1") is None
        assert db.get_agent("a1") is None
        assert db.get_messages("t1") == []


class TestAgents:
    def test_create_and_get(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "sub-task", "cursor", model="sonnet-4.6")
        agent = db.get_agent("a1")
        assert agent["role"] == "worker"
        assert agent["status"] == "pending"
        assert agent["attempts"] == 0

    def test_list_agents_by_team(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_team("t2", "task2", "claude")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.create_agent("a2", "t2", "worker", "t2", "claude")
        agents = db.list_agents(team_id="t1")
        assert len(agents) == 1
        assert agents[0]["id"] == "a1"

    def test_list_agents_by_status(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.create_agent("a2", "t1", "lead", "t1", "cursor")
        db.update_agent("a1", status="running")
        running = db.list_agents(status="running")
        assert len(running) == 1

    def test_update_agent(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.update_agent("a1", status="running", pid=12345, tmux_session="phalanx-t1-a1")
        agent = db.get_agent("a1")
        assert agent["status"] == "running"
        assert agent["pid"] == 12345

    def test_extra_fields(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor",
                        stall_seconds=300, max_retries=5)
        agent = db.get_agent("a1")
        assert agent["stall_seconds"] == 300
        assert agent["max_retries"] == 5


class TestMessages:
    def test_insert_and_get(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        msg_id = db.insert_message("t1", "user", "do this", agent_id="a1")
        assert msg_id is not None
        msgs = db.get_messages("t1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "do this"
        assert msgs[0]["delivered"] == 0

    def test_filter_by_agent(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.create_agent("a2", "t1", "worker", "t2", "cursor")
        db.insert_message("t1", "lead", "msg1", agent_id="a1")
        db.insert_message("t1", "lead", "msg2", agent_id="a2")
        msgs = db.get_messages("t1", agent_id="a1")
        assert len(msgs) == 1


class TestFileLocks:
    def test_acquire_and_release(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        assert db.acquire_lock("/src/foo.py", "t1", "a1", 1234) is True
        lock = db.get_lock("/src/foo.py")
        assert lock["agent_id"] == "a1"
        db.release_lock("/src/foo.py")
        assert db.get_lock("/src/foo.py") is None

    def test_duplicate_lock_fails(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.create_agent("a2", "t1", "worker", "t2", "cursor")
        db.acquire_lock("/src/foo.py", "t1", "a1", 1234)
        assert db.acquire_lock("/src/foo.py", "t1", "a2", 5678) is False

    def test_release_agent_locks(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.acquire_lock("/a.py", "t1", "a1", 100)
        db.acquire_lock("/b.py", "t1", "a1", 100)
        count = db.release_agent_locks("a1")
        assert count == 2
        assert db.list_locks("t1") == []

    def test_list_locks(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.acquire_lock("/a.py", "t1", "a1", 100)
        db.acquire_lock("/b.py", "t1", "a1", 100)
        assert len(db.list_locks("t1")) == 2


class TestEvents:
    def test_insert_and_get(self, db):
        db.create_team("t1", "task1", "cursor")
        eid = db.insert_event("heartbeat", team_id="t1", payload={"alive": True})
        assert eid is not None
        evts = db.get_events(team_id="t1")
        assert len(evts) == 1
        assert evts[0]["event_type"] == "heartbeat"

    def test_filter_by_type(self, db):
        db.create_team("t1", "task1", "cursor")
        db.insert_event("heartbeat", team_id="t1")
        db.insert_event("stall", team_id="t1")
        evts = db.get_events(team_id="t1", event_type="stall")
        assert len(evts) == 1


class TestGC:
    def test_stale_teams_empty(self, db):
        db.create_team("t1", "task1", "cursor")
        assert db.get_stale_teams() == []

    def test_stale_locks(self, db):
        db.create_team("t1", "task1", "cursor")
        db.create_agent("a1", "t1", "worker", "t1", "cursor")
        db.acquire_lock("/a.py", "t1", "a1", 99999)
        stale = db.get_stale_locks()
        assert len(stale) == 1


class TestTransaction:
    def test_rollback_on_error(self, db):
        db.create_team("t1", "task1", "cursor")
        try:
            with db.transaction() as conn:
                conn.execute("UPDATE teams SET status = 'dead' WHERE id = 't1'")
                raise ValueError("boom")
        except ValueError:
            pass
        assert db.get_team("t1")["status"] == "running"
