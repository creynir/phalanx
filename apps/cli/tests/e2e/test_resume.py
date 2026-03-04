"""E2E test: team stop and resume flow."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from phalanx.db import StateDB
from phalanx.team.create import create_team
from phalanx.team.orchestrator import stop_team


pytestmark = pytest.mark.e2e


class TestResumeFlow:
    @pytest.fixture
    def db(self, tmp_path):
        d = StateDB(db_path=tmp_path / "test.db")
        yield d

    @patch("phalanx.process.manager.ProcessManager.spawn")
    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0, create=True)
    def test_stop_preserves_data_for_resume(self, mock_locks, mock_spawn, db, tmp_path):
        mock_spawn.return_value = MagicMock(
            session_name="phalanx-test",
            pane_pid=12345,
            stream_log=tmp_path / "stream.log",
        )

        from phalanx.process.manager import ProcessManager
        from phalanx.monitor.heartbeat import HeartbeatMonitor

        process_manager = ProcessManager(tmp_path)
        heartbeat_monitor = HeartbeatMonitor(db)

        with patch("phalanx.team.create.get_phalanx_root", return_value=tmp_path, create=True):
            team_id, lead_id = create_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=process_manager,
                heartbeat_monitor=heartbeat_monitor,
                task="build feature",
                backend_name="cursor",
            )

        # Set chat_id to simulate a resumable session
        agents = db.list_agents(team_id=team_id)
        for agent in agents:
            db.update_agent(agent["id"], chat_id=f"chat-{agent['id']}")

        # Stop
        with patch(
            "phalanx.process.manager.ProcessManager.has_session", return_value=False, create=True
        ):
            stop_team(db, process_manager, team_id)

        # Verify data preserved
        team = db.get_team(team_id)
        assert team is not None
        assert team["status"] == "dead"

        agents_after = db.list_agents(team_id=team_id)
        assert len(agents_after) >= 1  # lead at minimum, maybe worker
        for agent in agents_after:
            assert agent["chat_id"] is not None
            assert agent["status"] == "dead"

    @patch("phalanx.process.manager.ProcessManager.spawn")
    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0, create=True)
    def test_gc_deletes_after_threshold(self, mock_locks, mock_spawn, db, tmp_path):
        mock_spawn.return_value = MagicMock(
            session_name="phalanx-test",
            pane_pid=12345,
            stream_log=tmp_path / "stream.log",
        )

        teams_dir = tmp_path / "teams"
        from phalanx.process.manager import ProcessManager
        from phalanx.monitor.heartbeat import HeartbeatMonitor

        process_manager = ProcessManager(tmp_path)
        heartbeat_monitor = HeartbeatMonitor(db)

        with patch("phalanx.team.create.get_phalanx_root", return_value=tmp_path, create=True):
            team_id, lead_id = create_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=process_manager,
                heartbeat_monitor=heartbeat_monitor,
                task="temporary task",
                backend_name="cursor",
            )

        # Stop and simulate 48h old
        with patch(
            "phalanx.process.manager.ProcessManager.has_session", return_value=False, create=True
        ):
            stop_team(db, process_manager, team_id)

        with db._connect() as conn:
            conn.execute(
                "UPDATE teams SET updated_at = unixepoch('now', '-48 hours') WHERE id = ?",
                (team_id,),
            )
            conn.commit()

        # Create team dir
        (teams_dir / team_id).mkdir(parents=True, exist_ok=True)

        # GC should clean it
        from phalanx.monitor.gc import run_gc

        with patch("phalanx.monitor.gc.run_gc", wraps=run_gc):
            cleaned = run_gc(db=db, phalanx_root=tmp_path, max_age_hours=24)
            assert len(cleaned) == 1

        assert db.get_team(team_id) is None
        assert not (teams_dir / team_id).exists()
