"""Integration tests for CLI commands using Click test runner."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from phalanx.cli import cli


pytestmark = pytest.mark.integration


@pytest.fixture
def runner():
    return CliRunner()


class TestVersion:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.3.4" in result.output


class TestHelp:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "create-team" in result.output
        assert "status" in result.output


class TestStatus:
    def test_status_runs(self, runner):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No active teams" in result.output or "Teams" in result.output

    def test_status_json(self, runner):
        result = runner.invoke(cli, ["--json-output", "status"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)


class TestConfig:
    pass


class TestModels:
    pass


class TestInit:
    def test_init_json(self, runner, tmp_path):
        # We need to change cwd to temp path for init to work there, or set PHALANX_ROOT
        import os

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / ".cursor").mkdir()
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
        finally:
            os.chdir(old_cwd)
