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
        assert "1.1" in result.output


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


class TestListTeams:
    def test_list_teams_empty(self, runner):
        result = runner.invoke(cli, ["--json-output", "list-teams"])
        assert result.exit_code == 0


class TestWriteArtifact:
    def test_write_artifact_missing_status(self, runner):
        result = runner.invoke(cli, ["write-artifact", "--output", '{"done": true}'])
        assert result.exit_code != 0

    def test_write_artifact_missing_env_vars(self, runner):
        result = runner.invoke(
            cli,
            ["write-artifact", "--status", "success", "--output", '{"done": true}'],
            env={"PHALANX_TEAM_ID": "", "PHALANX_AGENT_ID": ""},
        )
        assert result.exit_code != 0


class TestGC:
    def test_gc_command(self, runner):
        result = runner.invoke(cli, ["gc"])
        assert result.exit_code == 0


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


class TestRun:
    def test_run_missing_workflow(self, runner, tmp_path):
        """run command exits with code 1 when workflow file not found."""
        task_file = tmp_path / "task.yaml"
        task_file.write_text("id: test_task\ninstruction: Do something\n")

        result = runner.invoke(cli, ["run", "/nonexistent/workflow.yaml", "--task", str(task_file)])
        assert result.exit_code != 0
        assert "Error" in result.output or "not found" in result.output.lower()

    def test_run_missing_task(self, runner, tmp_path):
        """run command exits with code 1 when task file not found."""
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text(
            """
workflow:
  name: test_workflow
  entry: block_a
  transitions:
    - from: block_a
      to: null
blocks:
  block_a:
    type: placeholder
"""
        )

        result = runner.invoke(cli, ["run", str(workflow_file), "--task", "/nonexistent/task.yaml"])
        assert result.exit_code != 0

    def test_run_invalid_workflow_yaml(self, runner, tmp_path):
        """run command exits with code 1 when workflow YAML is invalid."""
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text("invalid: yaml: content: here")

        task_file = tmp_path / "task.yaml"
        task_file.write_text("id: test_task\ninstruction: Do something\n")

        result = runner.invoke(cli, ["run", str(workflow_file), "--task", str(task_file)])
        assert result.exit_code != 0
        assert "Error" in result.output

    def test_run_invalid_task_yaml(self, runner, tmp_path):
        """run command exits with code 1 when task YAML is invalid."""
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text(
            """
workflow:
  name: test_workflow
  entry: block_a
  transitions:
    - from: block_a
      to: null
blocks:
  block_a:
    type: placeholder
"""
        )

        task_file = tmp_path / "task.yaml"
        task_file.write_text("invalid: task: yaml")

        result = runner.invoke(cli, ["run", str(workflow_file), "--task", str(task_file)])
        assert result.exit_code != 0
        assert "Error" in result.output

    def test_run_task_option_required(self, runner, tmp_path):
        """run command requires --task option."""
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text(
            """
workflow:
  name: test_workflow
  entry: block_a
  transitions:
    - from: block_a
      to: null
blocks:
  block_a:
    type: placeholder
"""
        )

        result = runner.invoke(cli, ["run", str(workflow_file)])
        assert result.exit_code != 0
        assert "task" in result.output.lower()

    def test_run_simple_workflow_with_placeholder(self, runner, tmp_path):
        """run command successfully executes a simple workflow with placeholder block."""
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text(
            """
workflow:
  name: test_workflow
  entry: block_a
  transitions:
    - from: block_a
      to: null
blocks:
  block_a:
    type: placeholder
    description: Test placeholder block
"""
        )

        task_file = tmp_path / "task.yaml"
        task_file.write_text(
            "version: '1.0'\ntask:\n  id: test_task\n  instruction: Do something\n"
        )

        result = runner.invoke(cli, ["run", str(workflow_file), "--task", str(task_file)])
        assert result.exit_code == 0
        assert "Workflow execution completed successfully" in result.output
        assert "tokens" in result.output.lower()
        assert "cost" in result.output.lower()
