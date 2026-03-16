"""Tests for phalanx lock * subcommands (v2)."""
from __future__ import annotations

from click.testing import CliRunner

from phalanx.cli import cli


def test_lock_group_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["lock", "--help"])
    assert result.exit_code == 0
    assert "acquire" in result.output
    assert "release" in result.output
    assert "status" in result.output


def test_lock_acquire_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["lock", "acquire", "--help"])
    assert result.exit_code == 0
    # v2: usage line must contain "acquire", not just "lock FILE_PATH"
    assert "acquire" in result.output.split("\n")[0].lower()


def test_lock_acquire_requires_path():
    """lock acquire with no path should fail with missing argument."""
    runner = CliRunner()
    result = runner.invoke(cli, ["lock", "acquire"])
    assert result.exit_code != 0
    assert "missing argument" in result.output.lower()


def test_lock_release_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["lock", "release", "--help"])
    assert result.exit_code == 0
    assert "release" in result.output.split("\n")[0].lower()


def test_lock_release_requires_path():
    """lock release with no path should fail with missing argument."""
    runner = CliRunner()
    result = runner.invoke(cli, ["lock", "release"])
    assert result.exit_code != 0
    assert "missing argument" in result.output.lower()


def test_lock_status_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["lock", "status", "--help"])
    assert result.exit_code == 0
    assert "status" in result.output.split("\n")[0].lower()


def test_lock_status_no_args_needed():
    """lock status takes no required args — help exits 0."""
    runner = CliRunner()
    result = runner.invoke(cli, ["lock", "status", "--help"])
    assert result.exit_code == 0


# Old flat paths are gone in v2
def test_old_unlock_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["unlock", "--help"])
    assert result.exit_code != 0


def test_old_lock_status_flat_not_reachable():
    runner = CliRunner()
    result = runner.invoke(cli, ["lock-status", "--help"])
    assert result.exit_code != 0
