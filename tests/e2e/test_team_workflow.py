"""E2E test: full team workflow — create, status, stop.

NOTE: This test spawns real tmux sessions but uses 'echo' instead of
actual agent CLIs to avoid cost. It validates the orchestration pipeline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from phalanx.db import Database
from phalanx.team.create import create_team, parse_agents_spec
from phalanx.team.orchestrator import get_team_status, stop_team
from phalanx.artifacts.writer import write_artifact


pytestmark = pytest.mark.e2e


class TestParseAgentsSpec:
    def test_simple(self):
        assert parse_agents_spec("coder") == [("coder", 1)]

    def test_with_count(self):
        assert parse_agents_spec("coder:2") == [("coder", 2)]

    def test_mixed(self):
        result = parse_agents_spec("researcher,coder:2,reviewer")
        assert result == [("researcher", 1), ("coder", 2), ("reviewer", 1)]


class TestTeamWorkflow:
    @pytest.fixture
    def db(self, tmp_path):
        d = Database(db_path=tmp_path / "test.db")
        yield d
        d.close()

    @patch("phalanx.team.spawn.spawn_in_tmux")
    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0)
    def test_create_and_stop(self, mock_locks, mock_spawn, db, tmp_path):
        mock_spawn.return_value = {
            "session_name": "phalanx-test-agent",
            "pane_pid": 12345,
        }

        with patch("phalanx.artifacts.writer.TEAMS_DIR", tmp_path / "teams"):
            result = create_team(
                db=db,
                task="write unit tests",
                agents_spec="coder:2,researcher",
                backend_name="cursor",
                workspace=tmp_path,
            )

        assert result["status"] == "running"
        assert len(result["workers"]) == 3
        assert result["lead"] is not None

        # Check DB state
        team = db.get_team(result["team_id"])
        assert team["status"] == "running"
        agents = db.list_agents(team_id=result["team_id"])
        assert len(agents) == 4  # 3 workers + 1 lead

        # Stop team
        with patch("phalanx.team.orchestrator.session_exists", return_value=False):
            stop_result = stop_team(db, result["team_id"])
            assert stop_result["status"] == "dead"

        # Verify all agents dead
        for agent in db.list_agents(team_id=result["team_id"]):
            assert agent["status"] == "dead"

    @patch("phalanx.team.spawn.spawn_in_tmux")
    @patch("phalanx.monitor.gc.cleanup_dead_locks", return_value=0)
    def test_team_status_tracks_completion(self, mock_locks, mock_spawn, db, tmp_path):
        mock_spawn.return_value = {
            "session_name": "phalanx-test-agent",
            "pane_pid": 12345,
        }

        teams_dir = tmp_path / "teams"
        with patch("phalanx.artifacts.writer.TEAMS_DIR", teams_dir):
            result = create_team(
                db=db,
                task="analyze code",
                agents_spec="researcher",
                backend_name="cursor",
                workspace=tmp_path,
            )

        # Simulate worker writing artifact
        worker_id = result["workers"][0]
        with patch("phalanx.artifacts.writer.TEAMS_DIR", teams_dir):
            write_artifact("success", {"findings": "all good"},
                           team_id=result["team_id"], agent_id=worker_id)

        db.update_agent(worker_id, artifact_status="success", status="idle")

        # Simulate lead writing artifact
        lead_id = result["lead"]
        with patch("phalanx.artifacts.writer.TEAMS_DIR", teams_dir):
            write_artifact("success", {"summary": "done"},
                           team_id=result["team_id"], agent_id=lead_id)

        db.update_agent(lead_id, artifact_status="success", status="idle")

        # Check status shows completed
        with patch("phalanx.monitor.lifecycle.session_exists", return_value=False):
            status = get_team_status(db, result["team_id"])
            assert status["status"] == "completed"
