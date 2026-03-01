"""Tests for agent lifecycle state machine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from phalanx.db import Database
from phalanx.monitor.lifecycle import can_transition, transition_agent, check_agent_health


class TestCanTransition:
    def test_valid(self):
        assert can_transition("pending", "running") is True
        assert can_transition("running", "idle") is True
        assert can_transition("running", "stalled") is True
        assert can_transition("running", "dead") is True
        assert can_transition("dead", "running") is True  # resume

    def test_invalid(self):
        assert can_transition("pending", "dead") is False
        assert can_transition("failed", "running") is False
        assert can_transition("idle", "stalled") is False


class TestTransitionAgent:
    @pytest.fixture
    def db(self, tmp_path):
        d = Database(db_path=tmp_path / "test.db")
        d.create_team("t1", "task", "cursor")
        d.create_agent("a1", "t1", "worker", "task", "cursor")
        d.update_agent("a1", status="running")
        yield d
        d.close()

    def test_valid_transition(self, db):
        assert transition_agent(db, "a1", "idle") is True
        assert db.get_agent("a1")["status"] == "idle"

    def test_invalid_transition(self, db):
        assert transition_agent(db, "a1", "pending") is False
        assert db.get_agent("a1")["status"] == "running"

    def test_missing_agent(self, db):
        assert transition_agent(db, "nonexistent", "running") is False


class TestCheckAgentHealth:
    @pytest.fixture
    def db(self, tmp_path):
        d = Database(db_path=tmp_path / "test.db")
        d.create_team("t1", "task", "cursor")
        d.create_agent("a1", "t1", "worker", "task", "cursor",
                        tmux_session="phalanx-t1-a1")
        d.update_agent("a1", status="running")
        yield d
        d.close()

    @patch("phalanx.monitor.lifecycle.session_exists", return_value=True)
    def test_alive_agent(self, mock_exists, db):
        status = check_agent_health(db, "a1")
        assert status == "running"

    @patch("phalanx.monitor.lifecycle.session_exists", return_value=False)
    def test_dead_agent_no_artifact(self, mock_exists, db):
        status = check_agent_health(db, "a1")
        assert status == "dead"

    @patch("phalanx.monitor.lifecycle.session_exists", return_value=False)
    def test_idle_agent_with_artifact(self, mock_exists, db):
        db.update_agent("a1", artifact_status="success")
        status = check_agent_health(db, "a1")
        assert status == "idle"

    def test_already_dead(self, db):
        db.update_agent("a1", status="dead")
        status = check_agent_health(db, "a1")
        assert status == "dead"

    def test_missing_agent(self, db):
        assert check_agent_health(db, "nonexistent") == "unknown"
