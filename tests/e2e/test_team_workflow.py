"""E2E test: full team workflow — create, status, stop."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from phalanx.db import StateDB
from phalanx.team.create import create_team
from phalanx.team.orchestrator import stop_team


pytestmark = pytest.mark.e2e


class TestTeamWorkflow:
    @pytest.fixture
    def db(self, tmp_path):
        d = StateDB(db_path=tmp_path / "test.db")
        yield d

    @patch("phalanx.process.manager.ProcessManager.spawn")
    def test_create_and_stop(self, mock_spawn, db, tmp_path):
        mock_spawn.return_value = MagicMock(
            session_name="phalanx-test-agent",
            pane_pid=12345,
            stream_log=tmp_path / "stream.log",
            agent_id="test-agent-id",
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
                task="write unit tests",
                backend_name="cursor",
            )

        # Check DB state
        team = db.get_team(team_id)
        assert team is not None
        assert team["status"] == "running"
        agents = db.list_agents(team_id=team_id)
        assert len(agents) == 1

        # Stop team
        stop_team(db, process_manager, team_id)

        # Verify all agents dead
        team_after = db.get_team(team_id)
        assert team_after["status"] == "dead"
        for agent in db.list_agents(team_id=team_id):
            assert agent["status"] == "dead"
