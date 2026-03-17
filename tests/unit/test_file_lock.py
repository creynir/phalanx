"""Tests for advisory file locking."""

from __future__ import annotations

import os

import pytest

from phalanx.db import StateDB
from phalanx.comms.file_lock import (
    acquire_lock,
    release_lock,
)


@pytest.fixture
def db(tmp_path):
    d = StateDB(db_path=tmp_path / "test.db")
    d.create_team("t1", "task", "cursor")
    d.create_agent("a1", "t1", task="do work", role="agent", backend="cursor")
    d.create_agent("a2", "t1", task="do work", role="agent", backend="cursor")
    yield d


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
        # Ensure it can be acquired again
        assert acquire_lock(db, "/src/foo.py", "t1", "a2") is True


class TestStaleLocks:
    def test_acquire_overrides_dead_pid(self, db):
        # Acquire with a pid that doesn't exist
        db.acquire_lock("/x.py", "t1", "a1", 99999999)
        # Should succeed and override
        assert acquire_lock(db, "/x.py", "t1", "a2") is True

    def test_acquire_fails_live_pid(self, db):
        db.acquire_lock("/x.py", "t1", "a1", os.getpid())
        # Should fail because os.getpid() is alive
        assert acquire_lock(db, "/x.py", "t1", "a2") is False
