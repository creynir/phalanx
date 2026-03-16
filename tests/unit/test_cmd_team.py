"""Tests for phalanx team * subcommands (v2)."""
from __future__ import annotations

from click.testing import CliRunner

from phalanx.cli import cli


def test_team_group_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "--help"])
    assert result.exit_code == 0
    # Group help must list all subcommands
    assert "create" in result.output
    assert "list" in result.output
    assert "status" in result.output


def test_team_create_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert result.exit_code == 0


def test_team_create_has_task_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--task" in result.output


def test_team_create_has_config_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--config" in result.output


def test_team_create_has_agents_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--agents" in result.output


def test_team_create_has_backend_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--backend" in result.output


def test_team_create_has_model_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--model" in result.output


def test_team_create_has_idle_timeout_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--idle-timeout" in result.output


def test_team_create_has_max_runtime_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--max-runtime" in result.output


def test_team_create_has_worktree_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--worktree" in result.output


def test_team_create_has_auto_approve_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--auto-approve" in result.output


def test_team_create_has_example_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert "--example" in result.output


def test_team_create_example_prints_and_exits():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "create", "--example"])
    assert result.exit_code == 0
    # Should print JSON config example
    assert "{" in result.output


def test_team_list_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "list", "--help"])
    assert result.exit_code == 0


def test_team_status_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "status", "--help"])
    assert result.exit_code == 0


def test_team_status_optional_id():
    """team status accepts an optional positional team_id."""
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "status", "--help"])
    assert result.exit_code == 0
    assert "team_id" in result.output.lower() or "[" in result.output


def test_team_result_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "result", "--help"])
    assert result.exit_code == 0


def test_team_result_requires_id():
    """team result with no arg should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "result"])
    assert result.exit_code != 0


def test_team_costs_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "costs", "--help"])
    assert result.exit_code == 0


def test_team_debt_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "debt", "--help"])
    assert result.exit_code == 0


def test_team_stop_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "stop", "--help"])
    assert result.exit_code == 0


def test_team_stop_requires_id():
    """team stop with no arg should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "stop"])
    assert result.exit_code != 0


def test_team_resume_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "resume", "--help"])
    assert result.exit_code == 0


def test_team_resume_has_lead_only_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "resume", "--help"])
    assert "--lead-only" in result.output


def test_team_resume_has_auto_approve_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "resume", "--help"])
    assert "--auto-approve" in result.output


def test_team_broadcast_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "broadcast", "--help"])
    assert result.exit_code == 0


def test_team_broadcast_requires_id_and_text():
    """team broadcast with no args should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "broadcast"])
    assert result.exit_code != 0


def test_team_monitor_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "monitor", "--help"])
    assert result.exit_code == 0


def test_team_gc_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "gc", "--help"])
    assert result.exit_code == 0


def test_team_gc_has_older_than_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "gc", "--help"])
    assert "--older-than" in result.output


def test_team_gc_has_all_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["team", "gc", "--help"])
    assert "--all" in result.output


# Old flat paths are gone in v2
def test_old_create_team_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["create-team", "--help"])
    assert result.exit_code != 0


def test_old_list_teams_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["list-teams", "--help"])
    assert result.exit_code != 0


def test_old_team_status_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["team-status", "--help"])
    assert result.exit_code != 0


def test_old_stop_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["stop", "--help"])
    assert result.exit_code != 0


def test_old_resume_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["resume", "--help"])
    assert result.exit_code != 0


def test_old_gc_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["gc", "--help"])
    assert result.exit_code != 0


def test_old_broadcast_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["broadcast", "--help"])
    assert result.exit_code != 0
