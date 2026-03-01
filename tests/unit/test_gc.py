"""Tests for garbage collection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from phalanx.db import Database
from phalanx.monitor.gc import gc_check, cleanup_team


class TestCleanupTeam:
    @pytest.fixture
    def db(self, tmp_path):
        d = Database(db_path=tmp_path / "test.db")
        d.create_team("t1", "task", "cursor")
        d.create_agent("a1", "t1", "worker", "task", "cursor")
        yield d
        d.close()

    def test_cleanup_removes_dir(self, db, tmp_path):
        teams_dir = tmp_path / "teams"
        team_dir = teams_dir / "t1"
        team_dir.mkdir(parents=True)
        (team_dir / "data.json").write_text("{}")

        cleanup_team(db, "t1", teams_dir)
        assert not team_dir.exists()
        assert db.get_team("t1") is None
        assert db.get_agent("a1") is None

    def test_cleanup_nonexistent_dir(self, db, tmp_path):
        cleanup_team(db, "t1", tmp_path / "teams")
        assert db.get_team("t1") is None


class TestGCCheck:
    @pytest.fixture
    def db(self, tmp_path):
        d = Database(db_path=tmp_path / "test.db")
        yield d
        d.close()

    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0)
    def test_no_stale_teams(self, mock_locks, db, tmp_path):
        db.create_team("t1", "task", "cursor")
        cleaned = gc_check(db, teams_dir=tmp_path / "teams")
        assert cleaned == 0

    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0)
    def test_stale_team_cleaned(self, mock_locks, db, tmp_path):
        db.create_team("t1", "task", "cursor")
        db.update_team("t1", status="dead")
        # Force updated_at to be old
        db._get_conn().execute(
            "UPDATE teams SET updated_at = datetime('now', '-48 hours') WHERE id = 't1'"
        )
        db._get_conn().commit()

        teams_dir = tmp_path / "teams"
        (teams_dir / "t1").mkdir(parents=True)

        cleaned = gc_check(db, gc_hours=24, teams_dir=teams_dir)
        assert cleaned == 1
        assert db.get_team("t1") is None
