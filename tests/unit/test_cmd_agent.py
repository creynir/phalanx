"""Tests for phalanx agent * subcommands (v2)."""
from __future__ import annotations

from click.testing import CliRunner

from phalanx.cli import cli


def test_agent_group_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "--help"])
    assert result.exit_code == 0
    assert "status" in result.output
    assert "result" in result.output
    assert "done" in result.output


def test_agent_status_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "status", "--help"])
    assert result.exit_code == 0


def test_agent_status_optional_id():
    """agent status accepts an optional positional agent_id."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "status", "--help"])
    assert result.exit_code == 0


def test_agent_result_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "result", "--help"])
    assert result.exit_code == 0


def test_agent_result_requires_id():
    """agent result with no arg should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "result"])
    assert result.exit_code != 0


def test_agent_result_no_team_id_flag():
    """v2: agent result looks up team from DB, no --team-id required."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "result", "--help"])
    assert result.exit_code == 0
    assert "--team-id" not in result.output


def test_agent_stop_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "stop", "--help"])
    assert result.exit_code == 0


def test_agent_stop_requires_id():
    """agent stop with no arg should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "stop"])
    assert result.exit_code != 0


def test_agent_resume_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "resume", "--help"])
    assert result.exit_code == 0


def test_agent_resume_has_reply_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "resume", "--help"])
    assert "--reply" in result.output


def test_agent_resume_has_auto_approve_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "resume", "--help"])
    assert "--auto-approve" in result.output


def test_agent_monitor_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "monitor", "--help"])
    assert result.exit_code == 0


def test_agent_keys_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "keys", "--help"])
    assert result.exit_code == 0


def test_agent_keys_requires_id_and_keys():
    """agent keys with no args should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "keys"])
    assert result.exit_code != 0


def test_agent_keys_has_no_enter_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "keys", "--help"])
    assert "--no-enter" in result.output


def test_agent_done_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "done", "--help"])
    assert result.exit_code == 0


def test_agent_done_has_output_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "done", "--help"])
    assert "--output" in result.output


def test_agent_done_has_failed_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "done", "--help"])
    assert "--failed" in result.output


def test_agent_done_has_escalate_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "done", "--help"])
    assert "--escalate" in result.output


def test_agent_done_has_status_alias():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "done", "--help"])
    assert "--status" in result.output


def test_agent_done_requires_output():
    """agent done requires --output — should fail with no args."""
    runner = CliRunner()
    env = {"PHALANX_AGENT_ID": "test-agent", "PHALANX_TEAM_ID": "test-team"}
    result = runner.invoke(cli, ["agent", "done"], env=env)
    assert result.exit_code != 0


def test_agent_logs_requires_id():
    """agent logs with no arg should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "logs"])
    assert result.exit_code != 0


def test_agent_logs_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "logs", "--help"])
    assert result.exit_code == 0


def test_agent_logs_has_follow_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "logs", "--help"])
    assert "--follow" in result.output or "-f" in result.output


def test_agent_logs_has_lines_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "logs", "--help"])
    assert "--lines" in result.output


def test_agent_models_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "models", "--help"])
    assert result.exit_code == 0


def test_agent_models_has_backend_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "models", "--help"])
    assert "--backend" in result.output


def test_agent_models_requires_backend():
    """agent models with no backend should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "models"])
    assert result.exit_code != 0


# Old flat paths are gone in v2
def test_old_agent_status_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent-status", "--help"])
    assert result.exit_code != 0


def test_old_stop_agent_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["stop-agent", "--help"])
    assert result.exit_code != 0


def test_old_resume_agent_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["resume-agent", "--help"])
    assert result.exit_code != 0


def test_old_send_keys_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["send-keys", "--help"])
    assert result.exit_code != 0


def test_old_write_artifact_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["write-artifact", "--help"])
    assert result.exit_code != 0


def test_old_monitor_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["monitor", "--help"])
    assert result.exit_code != 0
