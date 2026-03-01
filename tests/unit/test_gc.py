"""Tests for garbage collection."""

from __future__ import annotations

import pytest

from phalanx.db import StateDB
from phalanx.monitor.gc import run_gc


class TestGCCheck:
    @pytest.fixture
    def db(self, tmp_path):
        d = StateDB(db_path=tmp_path / "test.db")
        yield d

    def test_no_stale_teams(self, db, tmp_path):
        db.create_team("t1", "task", "cursor")
        cleaned = run_gc(phalanx_root=tmp_path, db=db, max_age_hours=24)
        assert len(cleaned) == 0

    def test_stale_team_cleaned(self, db, tmp_path):
        db.create_team("t1", "task", "cursor")
        db.update_team_status("t1", status="dead")

        # Force updated_at to be old
        with db._connect() as conn:
            conn.execute(
                "UPDATE teams SET updated_at = unixepoch('now', '-48 hours') WHERE id = 't1'"
            )
            conn.commit()

        teams_dir = tmp_path / "teams"
        (teams_dir / "t1").mkdir(parents=True, exist_ok=True)

        cleaned = run_gc(phalanx_root=tmp_path, db=db, max_age_hours=24)
        assert len(cleaned) == 1
        assert "t1" in cleaned
        assert db.get_team("t1") is None
