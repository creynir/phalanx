"""Tests for phalanx feed * subcommands (v2)."""
from __future__ import annotations

from click.testing import CliRunner

from phalanx.cli import cli


def test_feed_group_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["feed", "--help"])
    assert result.exit_code == 0
    assert "read" in result.output
    assert "post" in result.output


def test_feed_read_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["feed", "read", "--help"])
    assert result.exit_code == 0
    # v2: usage line must say "feed read", not just "feed"
    assert "read" in result.output.split("\n")[0].lower()


def test_feed_read_team_id_positional():
    """team_id is positional in v2 (not --team-id option)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["feed", "read", "--help"])
    assert result.exit_code == 0
    # In v2, TEAM_ID is positional — must appear in usage
    assert "TEAM_ID" in result.output
    # And --team-id as an option must NOT exist
    assert "--team-id" not in result.output


def test_feed_read_has_limit_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["feed", "read", "--help"])
    assert result.exit_code == 0
    assert "--limit" in result.output
    assert "TEAM_ID" in result.output  # positional means it's a proper subcommand


def test_feed_read_has_since_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["feed", "read", "--help"])
    assert "--since" in result.output
    assert "TEAM_ID" in result.output  # v2 positional


def test_feed_read_uses_env_team_id():
    """feed read uses PHALANX_TEAM_ID env var if team_id not given as positional."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["feed", "read"], env={"PHALANX_TEAM_ID": "env-team-id"}
    )
    # Should NOT be a "missing argument" error (env var provides team_id)
    assert "missing argument" not in result.output.lower()
    # Should not be a "PHALANX_TEAM_ID required" error (env var was set)
    assert "team_id required" not in result.output.lower()


def test_feed_post_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["feed", "post", "--help"])
    assert result.exit_code == 0
    # v2: usage line must say "feed post"
    assert "post" in result.output.split("\n")[0].lower()


def test_feed_post_requires_text():
    """feed post with no text should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["feed", "post"])
    assert result.exit_code != 0


# Old flat paths are gone in v2
def test_old_post_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["post", "--help"])
    assert result.exit_code != 0
