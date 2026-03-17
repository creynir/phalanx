"""Regression tests for phalanx CLI bugfixes (v2 command paths).

Bug 1: `phalanx team resume <team_id>` only resumed the lead agent; all worker
       agents were left in the 'dead' state.

       FIX: The `team resume` command now defaults to waking ALL dead/suspended
       agents. A `--lead-only` flag preserves the old single-agent behaviour.

Bug 2: Agents in the `blocked_on_prompt` state could not be interacted with:
       - `phalanx msg agent` rejected them (status != "running")
       - `phalanx agent resume` rejected them (status not in dead/suspended)
       The only workaround was a manual `tmux send-keys` call.

       FIX: `msg agent` now accepts both "running" AND "blocked_on_prompt"
       agents. When the message is delivered to a blocked agent the status is
       updated to "running".

These tests ensure the fixes remain in place and the edge cases are covered.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from phalanx.cli import cli
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.process.manager import ProcessManager
from phalanx.team.orchestrator import resume_team, resume_single_agent


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


def _make_team(db: StateDB, team_id: str = "team-1", task: str = "test task") -> None:
    db.create_team(team_id, task)


def _make_agent(
    db: StateDB,
    agent_id: str,
    team_id: str,
    role: str = "agent",
    status: str = "dead",
    task: str = "do work",
    backend: str = "cursor",
) -> None:
    db.create_agent(agent_id, team_id, task, role=role, backend=backend)
    db.update_agent(agent_id, status=status)


# ---------------------------------------------------------------------------
# Bug 1 fix — resume_team wakes ALL dead/suspended agents by default
# ---------------------------------------------------------------------------


class TestBug1Fix_ResumeWakesAllAgents:
    """Regression tests: plain `phalanx team resume` now wakes ALL dead/suspended agents."""

    def test_resume_team_default_wakes_all_dead_agents(self, db, tmp_path):
        """resume_team(resume_all=True) wakes every dead/suspended agent."""
        _make_team(db, "t1")
        _make_agent(db, "lead-1", "t1", role="lead", status="dead")
        _make_agent(db, "worker-1", "t1", role="agent", status="dead")
        _make_agent(db, "worker-2", "t1", role="agent", status="dead")

        mock_pm = MagicMock(spec=ProcessManager)
        mock_hb = MagicMock(spec=HeartbeatMonitor)
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with (
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_gb.return_value = MagicMock()
            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=mock_pm,
                heartbeat_monitor=mock_hb,
                team_id="t1",
                resume_all=True,  # this is now the CLI default
            )

        assert set(result["resumed_agents"]) == {"lead-1", "worker-1", "worker-2"}
        for aid in ("lead-1", "worker-1", "worker-2"):
            assert db.get_agent(aid)["status"] == "running"

    def test_resume_team_lead_only_skips_workers(self, db, tmp_path):
        """resume_team(resume_all=False) wakes only the lead (--lead-only flag)."""
        _make_team(db, "t2")
        _make_agent(db, "lead-2", "t2", role="lead", status="dead")
        _make_agent(db, "worker-a", "t2", role="agent", status="dead")
        _make_agent(db, "worker-b", "t2", role="agent", status="dead")

        mock_pm = MagicMock(spec=ProcessManager)
        mock_hb = MagicMock(spec=HeartbeatMonitor)
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with (
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_gb.return_value = MagicMock()
            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=mock_pm,
                heartbeat_monitor=mock_hb,
                team_id="t2",
                resume_all=False,  # --lead-only path
            )

        assert result["resumed_agents"] == ["lead-2"]
        assert db.get_agent("worker-a")["status"] == "dead"
        assert db.get_agent("worker-b")["status"] == "dead"

    def test_resume_team_includes_suspended_agents(self, db, tmp_path):
        """resume_team wakes suspended agents (not just dead)."""
        _make_team(db, "t3")
        _make_agent(db, "lead-3", "t3", role="lead", status="dead")
        _make_agent(db, "worker-susp", "t3", role="agent", status="suspended")
        _make_agent(db, "worker-dead", "t3", role="agent", status="dead")

        mock_pm = MagicMock(spec=ProcessManager)
        mock_hb = MagicMock(spec=HeartbeatMonitor)
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with (
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_gb.return_value = MagicMock()
            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=mock_pm,
                heartbeat_monitor=mock_hb,
                team_id="t3",
                resume_all=True,
            )

        assert "worker-susp" in result["resumed_agents"]
        assert "worker-dead" in result["resumed_agents"]
        assert db.get_agent("worker-susp")["status"] == "running"
        assert db.get_agent("worker-dead")["status"] == "running"

    def test_resume_team_skips_already_running_agents(self, db, tmp_path):
        """resume_team does not re-spawn agents that are already running."""
        _make_team(db, "t4")
        _make_agent(db, "lead-4", "t4", role="lead", status="dead")
        _make_agent(db, "worker-running", "t4", role="agent", status="running")

        mock_pm = MagicMock(spec=ProcessManager)
        mock_hb = MagicMock(spec=HeartbeatMonitor)
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with (
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_gb.return_value = MagicMock()
            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=mock_pm,
                heartbeat_monitor=mock_hb,
                team_id="t4",
                resume_all=True,
            )

        assert "worker-running" not in result["resumed_agents"]
        assert "lead-4" in result["resumed_agents"]
        assert db.get_agent("worker-running")["status"] == "running"

    def test_cli_resume_default_wakes_all_workers(self, runner, tmp_path):
        """CLI `phalanx team resume <team>` without flags wakes ALL dead workers."""
        db_instance = StateDB(tmp_path / "state.db")
        _make_team(db_instance, "t-cli-1")
        _make_agent(db_instance, "lead-cli", "t-cli-1", role="lead", status="dead")
        _make_agent(db_instance, "worker-cli-1", "t-cli-1", role="agent", status="dead")
        _make_agent(db_instance, "worker-cli-2", "t-cli-1", role="agent", status="dead")

        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
            patch("phalanx.team.orchestrator.ProcessManager") as mock_pm_cls,
            patch("phalanx.team.orchestrator.HeartbeatMonitor"),
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_cfg.return_value = MagicMock(
                idle_timeout=1800,
                max_runtime=1800,
                default_backend="cursor",
                default_model=None,
            )
            mock_pm = MagicMock()
            mock_pm.spawn.return_value = mock_proc
            mock_pm_cls.return_value = mock_pm
            mock_gb.return_value = MagicMock()

            result = runner.invoke(cli, ["--root", str(tmp_path), "team", "resume", "t-cli-1"])

        assert result.exit_code == 0, f"team resume failed: {result.output}"
        # FIX VERIFIED: workers are now running after a plain resume
        assert db_instance.get_agent("worker-cli-1")["status"] == "running"
        assert db_instance.get_agent("worker-cli-2")["status"] == "running"
        assert db_instance.get_agent("lead-cli")["status"] == "running"

    def test_cli_resume_lead_only_flag_leaves_workers_dead(self, runner, tmp_path):
        """CLI `phalanx team resume --lead-only <team>` only wakes the lead."""
        db_instance = StateDB(tmp_path / "state.db")
        _make_team(db_instance, "t-cli-2")
        _make_agent(db_instance, "lead-cli2", "t-cli-2", role="lead", status="dead")
        _make_agent(db_instance, "worker-cli-a", "t-cli-2", role="agent", status="dead")
        _make_agent(db_instance, "worker-cli-b", "t-cli-2", role="agent", status="dead")

        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
            patch("phalanx.team.orchestrator.ProcessManager") as mock_pm_cls,
            patch("phalanx.team.orchestrator.HeartbeatMonitor"),
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_cfg.return_value = MagicMock(
                idle_timeout=1800,
                max_runtime=1800,
                default_backend="cursor",
                default_model=None,
            )
            mock_pm = MagicMock()
            mock_pm.spawn.return_value = mock_proc
            mock_pm_cls.return_value = mock_pm
            mock_gb.return_value = MagicMock()

            result = runner.invoke(
                cli, ["--root", str(tmp_path), "team", "resume", "--lead-only", "t-cli-2"]
            )

        assert result.exit_code == 0, f"team resume --lead-only failed: {result.output}"
        assert db_instance.get_agent("lead-cli2")["status"] == "running"
        assert db_instance.get_agent("worker-cli-a")["status"] == "dead"
        assert db_instance.get_agent("worker-cli-b")["status"] == "dead"


# ---------------------------------------------------------------------------
# Bug 2 fix — msg agent and agent resume accept blocked_on_prompt agents
# ---------------------------------------------------------------------------


class TestBug2Fix_BlockedOnPromptAgents:
    """Regression tests: blocked_on_prompt agents are now reachable via CLI."""

    def test_message_agent_delivers_to_blocked_on_prompt(self, runner, tmp_path):
        """msg agent succeeds for blocked_on_prompt agents (fix verified)."""
        db_instance = StateDB(tmp_path / "state.db")
        _make_team(db_instance, "t-blk")
        _make_agent(
            db_instance, "blocked-agent", "t-blk", role="agent", status="blocked_on_prompt"
        )

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
            patch("phalanx.comms.messaging.deliver_message", return_value=True),
        ):
            mock_cfg.return_value = MagicMock()
            result = runner.invoke(
                cli,
                ["--root", str(tmp_path), "msg", "agent", "blocked-agent", "y"],
            )

        # FIX VERIFIED: msg agent now accepts blocked_on_prompt
        assert result.exit_code == 0, (
            f"msg agent should accept blocked_on_prompt agents: {result.output}"
        )

    def test_message_agent_rejects_dead_agent(self, runner, tmp_path):
        """msg agent still rejects dead agents (unchanged behaviour)."""
        db_instance = StateDB(tmp_path / "state.db")
        _make_team(db_instance, "t-dead")
        _make_agent(db_instance, "dead-agent", "t-dead", role="agent", status="dead")

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
        ):
            mock_cfg.return_value = MagicMock()

            result = runner.invoke(
                cli,
                ["--root", str(tmp_path), "msg", "agent", "dead-agent", "hello"],
            )

        assert result.exit_code != 0
        assert "dead" in result.output or "dead" in (result.stderr or "")

    def test_message_agent_rejects_suspended_agent(self, runner, tmp_path):
        """msg agent still rejects suspended agents (unchanged behaviour)."""
        db_instance = StateDB(tmp_path / "state.db")
        _make_team(db_instance, "t-susp")
        _make_agent(db_instance, "susp-agent", "t-susp", role="agent", status="suspended")

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
        ):
            mock_cfg.return_value = MagicMock()

            result = runner.invoke(
                cli,
                ["--root", str(tmp_path), "msg", "agent", "susp-agent", "hello"],
            )

        assert result.exit_code != 0

    def test_message_agent_blocked_updates_status_to_running(self, runner, tmp_path):
        """Successful message delivery to blocked agent updates status to running."""
        db_instance = StateDB(tmp_path / "state.db")
        _make_team(db_instance, "t-status")
        _make_agent(
            db_instance, "blocked-status", "t-status", role="agent", status="blocked_on_prompt"
        )

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
            patch("phalanx.comms.messaging.deliver_message", return_value=True),
        ):
            mock_cfg.return_value = MagicMock()
            result = runner.invoke(
                cli,
                ["--root", str(tmp_path), "msg", "agent", "blocked-status", "y"],
            )

        assert result.exit_code == 0
        # After successful delivery, status should be updated to running
        assert db_instance.get_agent("blocked-status")["status"] == "running"

    def test_resume_agent_rejects_blocked_on_prompt(self, db, tmp_path):
        """agent resume still raises for blocked_on_prompt (it has a live session)."""
        _make_team(db, "t-blk2")
        _make_agent(db, "blocked-2", "t-blk2", role="agent", status="blocked_on_prompt")

        mock_pm = MagicMock(spec=ProcessManager)
        mock_hb = MagicMock(spec=HeartbeatMonitor)

        with pytest.raises(ValueError) as exc_info:
            resume_single_agent(
                phalanx_root=tmp_path,
                db=db,
                process_manager=mock_pm,
                heartbeat_monitor=mock_hb,
                agent_id="blocked-2",
            )

        assert "blocked_on_prompt" in str(exc_info.value)

    def test_send_keys_command_available_for_blocked_agents(self, runner):
        """agent keys CLI command is available as the low-level unblock mechanism."""
        result = runner.invoke(cli, ["agent", "keys", "--help"])
        assert result.exit_code == 0
        assert "keys" in result.output.lower() or "keystrokes" in result.output.lower()

    def test_message_agent_cmd_help_mentions_blocked_on_prompt(self, runner):
        """msg agent help documents messaging agents."""
        result = runner.invoke(cli, ["msg", "agent", "--help"])
        assert result.exit_code == 0

    def test_message_agent_status_guard_allows_running_and_blocked(self, runner, tmp_path):
        """msg agent CLI status guard now permits 'running' AND 'blocked_on_prompt'."""
        db_instance = StateDB(tmp_path / "state.db")
        _make_team(db_instance, "t-guard")

        for agent_id, status in [
            ("agent-running", "running"),
            ("agent-blocked", "blocked_on_prompt"),
        ]:
            _make_agent(db_instance, agent_id, "t-guard", role="agent", status=status)

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
            patch("phalanx.comms.messaging.deliver_message", return_value=True),
        ):
            mock_cfg.return_value = MagicMock()

            for agent_id in ("agent-running", "agent-blocked"):
                result = runner.invoke(
                    cli,
                    ["--root", str(tmp_path), "msg", "agent", agent_id, "hello"],
                )
                assert result.exit_code == 0, (
                    f"msg agent should accept {agent_id} (status={agent_id.split('-')[1]}): "
                    f"{result.output}"
                )


# ---------------------------------------------------------------------------
# Bug 1 & Bug 2 interaction — fixing Bug 1 must not disturb blocked agents
# ---------------------------------------------------------------------------


class TestBug1AndBug2Interaction:
    """Ensure the Bug 1 fix does not accidentally re-spawn blocked_on_prompt agents."""

    def test_resume_all_skips_blocked_on_prompt_workers(self, db, tmp_path):
        """resume_team(resume_all=True) does NOT re-spawn blocked_on_prompt agents.

        blocked_on_prompt agents still have a live tmux session. Killing and
        re-spawning them would lose the prompt context. They should be skipped.
        """
        _make_team(db, "t-interaction")
        _make_agent(db, "lead-i", "t-interaction", role="lead", status="dead")
        _make_agent(db, "worker-dead", "t-interaction", role="agent", status="dead")
        _make_agent(
            db, "worker-blocked", "t-interaction", role="agent", status="blocked_on_prompt"
        )

        mock_pm = MagicMock(spec=ProcessManager)
        mock_hb = MagicMock(spec=HeartbeatMonitor)
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with (
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_gb.return_value = MagicMock()
            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=mock_pm,
                heartbeat_monitor=mock_hb,
                team_id="t-interaction",
                resume_all=True,
            )

        assert "worker-blocked" not in result["resumed_agents"]
        assert "lead-i" in result["resumed_agents"]
        assert "worker-dead" in result["resumed_agents"]
        assert db.get_agent("worker-blocked")["status"] == "blocked_on_prompt"

    def test_team_status_after_partial_resume(self, db, tmp_path):
        """Team status becomes 'running' even when some agents remain blocked."""
        _make_team(db, "t-partial")
        _make_agent(db, "lead-p", "t-partial", role="lead", status="dead")
        _make_agent(db, "worker-p-blocked", "t-partial", role="agent", status="blocked_on_prompt")

        mock_pm = MagicMock(spec=ProcessManager)
        mock_hb = MagicMock(spec=HeartbeatMonitor)
        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"
        mock_pm.spawn.return_value = mock_proc

        with (
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
        ):
            mock_gb.return_value = MagicMock()
            result = resume_team(
                phalanx_root=tmp_path,
                db=db,
                process_manager=mock_pm,
                heartbeat_monitor=mock_hb,
                team_id="t-partial",
                resume_all=True,
            )

        assert "lead-p" in result["resumed_agents"]
        assert "worker-p-blocked" not in result["resumed_agents"]
        team = db.get_team("t-partial")
        assert team["status"] == "running"


# ---------------------------------------------------------------------------
# E2E Workflows (Idle Timeout -> Resume -> Message)
# ---------------------------------------------------------------------------


class TestE2EIdleResumeMessageFlow:
    """End-to-end integration test simulating the real-world use case where a team
    goes idle, and is later resumed with new instructions."""

    def test_idle_timeout_resume_and_message_chain(self, runner, tmp_path):
        """Simulate a team that went idle (suspended/dead), then run `team resume`
        followed by `msg lead`.
        """
        db_instance = StateDB(tmp_path / "state.db")
        # 1. Simulate the state after an idle timeout
        _make_team(db_instance, "team-e2e")
        # In an idle timeout, the lead might be suspended, workers might be dead or suspended.
        _make_agent(db_instance, "lead-e2e", "team-e2e", role="lead", status="suspended")
        _make_agent(db_instance, "worker-e2e", "team-e2e", role="agent", status="dead")

        mock_proc = MagicMock()
        mock_proc.stream_log = tmp_path / "stream.log"

        with (
            patch("phalanx.db.StateDB", return_value=db_instance),
            patch("phalanx.config.load_config") as mock_cfg,
            patch("phalanx.team.orchestrator.ProcessManager") as mock_pm_cls,
            patch("phalanx.team.orchestrator.HeartbeatMonitor"),
            patch("phalanx.backends.get_backend") as mock_gb,
            patch("phalanx.team.create._spawn_team_monitor"),
            patch("phalanx.comms.messaging.deliver_message", return_value=True) as mock_deliver,
        ):
            mock_cfg.return_value = MagicMock(
                idle_timeout=1800,
                max_runtime=1800,
                default_backend="cursor",
                default_model=None,
            )
            mock_pm = MagicMock()
            mock_pm.spawn.return_value = mock_proc
            mock_pm_cls.return_value = mock_pm
            mock_gb.return_value = MagicMock()

            # 2. Run the `team resume` command
            result_resume = runner.invoke(
                cli, ["--root", str(tmp_path), "team", "resume", "team-e2e"]
            )
            assert result_resume.exit_code == 0, f"team resume failed: {result_resume.output}"

            # Verify agents are woken up
            assert db_instance.get_agent("lead-e2e")["status"] == "running"
            assert db_instance.get_agent("worker-e2e")["status"] == "running"

            # 3. Run the `msg lead` command
            result_msg = runner.invoke(
                cli, ["--root", str(tmp_path), "msg", "lead", "team-e2e", "Do more work"]
            )
            assert result_msg.exit_code == 0, f"msg lead failed: {result_msg.output}"
            assert "Message delivered to team lead (lead-e2e)" in result_msg.output

            # Verify the message delivery system was invoked
            from unittest.mock import ANY

            mock_deliver.assert_called_once_with(ANY, "lead-e2e", "Do more work")
