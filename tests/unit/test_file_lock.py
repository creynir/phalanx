"""Tests for advisory file locking."""

from __future__ import annotations

import os

import pytest

from phalanx.db import Database
from phalanx.comms.file_lock import (
    acquire_lock,
    release_lock,
    release_agent_locks,
    cleanup_dead_locks,
)


@pytest.fixture
def db(tmp_path):
    d = Database(db_path=tmp_path / "test.db")
    d.create_team("t1", "task", "cursor")
    d.create_agent("a1", "t1", "worker", "task", "cursor")
    d.create_agent("a2", "t1", "worker", "task", "cursor")
    yield d
    d.close()


class TestAcquireLock:
    def test_acquire_success(self, db):
        assert acquire_lock(db, "/src/foo.py", "t1", "a1") is True

    def test_acquire_conflict(self, db):
        acquire_lock(db, "/src/foo.py", "t1", "a1")
        assert acquire_lock(db, "/src/foo.py", "t1", "a2") is False


class TestReleaseLock:
    def test_release(self, db):
        acquire_lock(db, "/src/foo.py", "t1", "a1")
        release_lock(db, "/src/foo.py")
        assert db.get_lock("/src/foo.py") is None

    def test_release_agent_locks(self, db):
        acquire_lock(db, "/a.py", "t1", "a1")
        acquire_lock(db, "/b.py", "t1", "a1")
        count = release_agent_locks(db, "a1")
        assert count == 2


class TestCleanupDeadLocks:
    def test_cleanup_dead_pid(self, db):
        db.acquire_lock("/x.py", "t1", "a1", 99999999)
        cleaned = cleanup_dead_locks(db)
        assert cleaned == 1
        assert db.get_lock("/x.py") is None

    def test_keep_live_pid(self, db):
        db.acquire_lock("/x.py", "t1", "a1", os.getpid())
        cleaned = cleanup_dead_locks(db)
        assert cleaned == 0
        assert db.get_lock("/x.py") is not None
