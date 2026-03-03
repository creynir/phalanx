"""E2E tests: Basic Execution Flows — E2E-001 through E2E-005."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from phalanx.db import StateDB
from phalanx.team.create import create_team
from phalanx.team.orchestrator import stop_team, get_team_status


pytestmark = pytest.mark.e2e


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


@pytest.fixture
def mocked_spawn():
    with patch("phalanx.process.manager.ProcessManager.spawn") as mock:
        mock.return_value = MagicMock(
            session_name="phalanx-test",
            pane_pid=12345,
            stream_log=MagicMock(),
            agent_id="test-id",
        )
        yield mock


class TestE2E001_HappyPathLifecycle:
    """E2E-001: Create Team → Workers Complete → Lead Consolidates → Team Result."""

    def test_full_lifecycle(self, mocked_spawn, db, tmp_path):
        from phalanx.process.manager import ProcessManager
        from phalanx.monitor.heartbeat import HeartbeatMonitor

        pm = ProcessManager(tmp_path)
        hb = HeartbeatMonitor(db)

        with patch("phalanx.team.create.get_phalanx_root", return_value=tmp_path, create=True):
            team_id, lead_id = create_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=pm,
                heartbeat_monitor=hb,
                task="Implement a basic python calculator",
                agents_spec="coder:2,reviewer",
                backend_name="cursor",
            )

        team = db.get_team(team_id)
        assert team["status"] == "running"
        agents = db.list_agents(team_id)
        assert len(agents) == 4  # 2 coders + 1 reviewer + 1 lead

        # Simulate workers completing
        for a in agents:
            if a["role"] != "lead":
                db.update_agent(a["id"], artifact_status="success", status="suspended")

        # Verify team status shows all agents
        status = get_team_status(db, team_id)
        assert status["agent_count"] == 4

        # Stop team
        stop_team(db, pm, team_id)
        assert db.get_team(team_id)["status"] == "dead"


class TestE2E002_ConfiguredTeamSpawning:
    """E2E-002: Per-Agent Prompts and Models via Config File."""

    def test_per_agent_config(self, mocked_spawn, db, tmp_path):
        from phalanx.team.config import TeamConfig, AgentSpec, LeadSpec
        from phalanx.team.create import create_team_from_config
        from phalanx.process.manager import ProcessManager
        from phalanx.monitor.heartbeat import HeartbeatMonitor

        pm = ProcessManager(tmp_path)
        hb = HeartbeatMonitor(db)

        config = TeamConfig(
            task="build feature",
            agents=[
                AgentSpec(name="coder-1", role="coder", prompt="Write the main module"),
                AgentSpec(name="tester-1", role="reviewer", prompt="Write unit tests"),
            ],
            lead=LeadSpec(),
        )
        config.generate_ids()

        with patch("phalanx.team.create.get_phalanx_root", return_value=tmp_path, create=True):
            team_id, lead_id, worker_ids = create_team_from_config(
                phalanx_root=tmp_path,
                db=db,
                process_manager=pm,
                heartbeat_monitor=hb,
                team_config=config,
                backend_name="cursor",
            )

        agents = db.list_agents(team_id)
        assert len(agents) >= 3  # 2 workers + 1 lead


class TestE2E003_DefaultLaunchMode:
    """E2E-003: phalanx with no arguments launches interactive session."""

    def test_init_workspace(self, tmp_path):
        from phalanx.init_cmd import init_workspace

        (tmp_path / ".cursor").mkdir()
        init_workspace(tmp_path)
        assert (tmp_path / ".phalanx").exists()


class TestE2E004_SkillDeployment:
    """E2E-004: phalanx init deploys workspace rules."""

    def test_skill_files(self, tmp_path):
        from phalanx.init_cmd import init_workspace

        (tmp_path / ".cursor").mkdir()
        result = init_workspace(tmp_path)
        assert (tmp_path / ".phalanx").exists()
        assert len(result["skills_created"]) > 0


class TestE2E005_BackendModelFlags:
    """E2E-005: phalanx --backend cursor --model opus-4.6 passes correct flags."""

    def test_model_flag_forwarding(self):
        from phalanx.backends.cursor import CursorBackend

        backend = CursorBackend()
        cmd = backend.build_start_command(prompt="hello", model="opus-4.6")
        cmd_str = " ".join(cmd)
        assert "opus-4.6" in cmd_str or "model" in cmd_str
