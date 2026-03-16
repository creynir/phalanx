"""Tests for phalanx msg * subcommands (v2)."""
from __future__ import annotations

from click.testing import CliRunner

from phalanx.cli import cli


def test_msg_group_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["msg", "--help"])
    assert result.exit_code == 0
    assert "lead" in result.output
    assert "agent" in result.output


def test_msg_lead_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["msg", "lead", "--help"])
    assert result.exit_code == 0


def test_msg_lead_requires_team_id_and_text():
    """msg lead with no args should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["msg", "lead"])
    assert result.exit_code != 0


def test_msg_lead_requires_text():
    """msg lead with only team_id should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["msg", "lead", "some-team-id"])
    assert result.exit_code != 0


def test_msg_agent_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["msg", "agent", "--help"])
    assert result.exit_code == 0


def test_msg_agent_requires_agent_id_and_text():
    """msg agent with no args should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["msg", "agent"])
    assert result.exit_code != 0


def test_msg_agent_requires_text():
    """msg agent with only agent_id should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["msg", "agent", "some-agent-id"])
    assert result.exit_code != 0


# Old flat paths are gone in v2
def test_old_message_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["message", "--help"])
    assert result.exit_code != 0


def test_old_message_agent_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["message-agent", "--help"])
    assert result.exit_code != 0
