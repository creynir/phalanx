"""Tests for stall detection and retry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from phalanx.db import Database
from phalanx.monitor.stall import compute_backoff, handle_stall


class TestComputeBackoff:
    def test_first_attempt(self):
        assert compute_backoff(0) == 30

    def test_second_attempt(self):
        assert compute_backoff(1) == 60

    def test_capped(self):
        assert compute_backoff(10) == 300

    def test_custom_base(self):
        assert compute_backoff(0, base=10) == 10


class TestHandleStall:
    @pytest.fixture
    def db(self, tmp_path):
        d = Database(db_path=tmp_path / "test.db")
        d.create_team("t1", "task", "cursor")
        d.create_agent("a1", "t1", "worker", "task", "cursor",
                        tmux_session="phalanx-t1-a1", max_retries=3)
        yield d
        d.close()

    @patch("phalanx.monitor.stall.kill_session")
    def test_retry_on_first_stall(self, mock_kill, db):
        result = handle_stall(db, "a1", "t1")
        assert result == "retrying"
        agent = db.get_agent("a1")
        assert agent["attempts"] == 1
        assert agent["status"] == "stalled"

    @patch("phalanx.monitor.stall.kill_session")
    def test_fail_after_max_retries(self, mock_kill, db):
        db.update_agent("a1", attempts=2)
        result = handle_stall(db, "a1", "t1")
        assert result == "failed"
        assert db.get_agent("a1")["status"] == "failed"

    @patch("phalanx.monitor.stall.kill_session")
    def test_missing_agent(self, mock_kill, db):
        result = handle_stall(db, "nonexistent", "t1")
        assert result == "failed"
