"""Tests for top-level CLI entry point (v2)."""
from __future__ import annotations

from click.testing import CliRunner

from phalanx.cli import cli


def test_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "phalanx" in result.output.lower()


def test_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0


def test_init_command_exists():
    """init command must exist in v2."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--help"])
    assert result.exit_code == 0
    assert "init" in result.output.lower()


def test_global_root_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "--root" in result.output


def test_global_json_output_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "--json-output" in result.output


def test_global_verbose_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "--verbose" in result.output


# Old flat commands are gone in v2
def test_old_flat_create_team_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["create-team", "--help"])
    assert result.exit_code != 0


def test_old_flat_list_teams_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["list-teams", "--help"])
    assert result.exit_code != 0


def test_old_flat_team_status_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["team-status", "--help"])
    assert result.exit_code != 0


def test_old_flat_agent_status_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent-status", "--help"])
    assert result.exit_code != 0


def test_old_flat_stop_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["stop", "--help"])
    assert result.exit_code != 0


def test_old_flat_post_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["post", "--help"])
    assert result.exit_code != 0


def test_old_flat_unlock_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["unlock", "--help"])
    assert result.exit_code != 0


def test_old_flat_message_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["message", "--help"])
    assert result.exit_code != 0


def test_old_flat_write_artifact_removed():
    runner = CliRunner()
    result = runner.invoke(cli, ["write-artifact", "--help"])
    assert result.exit_code != 0
