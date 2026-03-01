"""Integration tests for CLI commands using Click test runner."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from phalanx.cli import main


pytestmark = pytest.mark.integration


@pytest.fixture
def runner():
    return CliRunner()


class TestVersion:
    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1." in result.output


class TestHelp:
    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "create-team" in result.output
        assert "status" in result.output


class TestStatus:
    def test_status_runs(self, runner):
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "No active teams" in result.output or "Teams" in result.output

    def test_status_json(self, runner):
        result = runner.invoke(main, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)


class TestConfig:
    def test_config_show(self, runner):
        result = runner.invoke(main, ["config", "show"])
        assert result.exit_code == 0
        assert "defaults.backend" in result.output

    def test_config_show_json(self, runner):
        result = runner.invoke(main, ["config", "show", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "models" in data


class TestModels:
    def test_models_show(self, runner):
        result = runner.invoke(main, ["models", "show"])
        assert result.exit_code == 0
        assert "cursor" in result.output

    def test_models_show_json(self, runner):
        result = runner.invoke(main, ["models", "show", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "cursor" in data

    def test_models_update(self, runner):
        result = runner.invoke(main, ["models", "update", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "available_backends" in data


class TestInit:
    def test_init_json(self, runner, tmp_path):
        (tmp_path / ".cursor").mkdir()
        result = runner.invoke(main, ["init", "--workspace", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "cursor" in data["ides_detected"]
