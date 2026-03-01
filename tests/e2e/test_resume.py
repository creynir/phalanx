"""E2E test: team stop and resume flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from phalanx.db import Database
from phalanx.team.create import create_team
from phalanx.team.orchestrator import stop_team


pytestmark = pytest.mark.e2e


class TestResumeFlow:
    @pytest.fixture
    def db(self, tmp_path):
        d = Database(db_path=tmp_path / "test.db")
        yield d
        d.close()

    @patch("phalanx.team.spawn.spawn_in_tmux")
    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0)
    def test_stop_preserves_data_for_resume(self, mock_locks, mock_spawn, db, tmp_path):
        mock_spawn.return_value = {
            "session_name": "phalanx-test",
            "pane_pid": 12345,
        }

        with patch("phalanx.artifacts.writer.TEAMS_DIR", tmp_path / "teams"):
            result = create_team(
                db=db,
                task="build feature",
                agents_spec="coder",
                backend_name="cursor",
                workspace=tmp_path,
            )

        team_id = result["team_id"]

        # Set chat_id to simulate a resumable session
        agents = db.list_agents(team_id=team_id)
        for agent in agents:
            db.update_agent(agent["id"], chat_id=f"chat-{agent['id']}")

        # Stop
        with patch("phalanx.team.orchestrator.session_exists", return_value=False):
            stop_team(db, team_id)

        # Verify data preserved
        team = db.get_team(team_id)
        assert team is not None
        assert team["status"] == "dead"

        agents_after = db.list_agents(team_id=team_id)
        assert len(agents_after) == 2  # worker + lead
        for agent in agents_after:
            assert agent["chat_id"] is not None
            assert agent["status"] == "dead"

    @patch("phalanx.team.spawn.spawn_in_tmux")
    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0)
    def test_gc_deletes_after_threshold(self, mock_locks, mock_spawn, db, tmp_path):
        mock_spawn.return_value = {
            "session_name": "phalanx-test",
            "pane_pid": 12345,
        }

        teams_dir = tmp_path / "teams"
        with patch("phalanx.artifacts.writer.TEAMS_DIR", teams_dir):
            result = create_team(
                db=db,
                task="temporary task",
                agents_spec="coder",
                backend_name="cursor",
                workspace=tmp_path,
            )

        team_id = result["team_id"]

        # Stop and simulate 48h old
        with patch("phalanx.team.orchestrator.session_exists", return_value=False):
            stop_team(db, team_id)

        db._get_conn().execute(
            "UPDATE teams SET updated_at = datetime('now', '-48 hours') WHERE id = ?",
            (team_id,),
        )
        db._get_conn().commit()

        # Create team dir
        (teams_dir / team_id).mkdir(parents=True)

        # GC should clean it
        from phalanx.monitor.gc import gc_check
        with patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0):
            cleaned = gc_check(db, gc_hours=24, teams_dir=teams_dir)
            assert cleaned == 1

        assert db.get_team(team_id) is None
        assert not (teams_dir / team_id).exists()
