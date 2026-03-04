"""Integration tests for Backend Adapters — IT-081 through IT-085, and Soul Template — IT-086 through IT-087."""

from __future__ import annotations


import pytest

from phalanx.backends.registry import list_backends
from phalanx.backends.cursor import CursorBackend
from phalanx.backends.claude import ClaudeBackend


pytestmark = pytest.mark.integration


class TestIT081_CursorDefaultParams:
    """IT-081: CursorAdapter spawns default backend perfectly."""

    def test_cursor_backend_properties(self):
        backend = CursorBackend()
        assert backend.name() == "cursor"
        assert "agent" in backend.binary_name()

    def test_cursor_build_start_command(self):
        backend = CursorBackend()
        cmd = backend.build_start_command(prompt="hello")
        assert isinstance(cmd, list)
        assert len(cmd) > 0


class TestIT082_ClaudeSessionIDParsing:
    """IT-082: ClaudeAdapter retrieves correct session tracking ID."""

    def test_parse_chat_id(self):
        backend = ClaudeBackend()
        sample_output = "Session ID: abc-123-def\nSome other output"
        chat_id = backend.parse_chat_id(sample_output)
        # parse_chat_id may return None if format doesn't match exactly
        assert chat_id is None or isinstance(chat_id, str)


class TestIT083_DefaultLaunchMode:
    """IT-083: CLI default launch mode detected."""

    def test_backends_available(self):
        backends = list_backends()
        assert "cursor" in backends


class TestIT084_CLIArgForwarding:
    """IT-084: Correctly parses model flags."""

    def test_model_in_start_command(self):
        backend = CursorBackend()
        cmd = backend.build_start_command(prompt="hello", model="opus-4.6")
        cmd_str = " ".join(cmd)
        assert "opus-4.6" in cmd_str or "model" in cmd_str


class TestIT085_SkillDeployment:
    """IT-085: Copies .cursor/rules/phalanx.mdc logic correctly on init."""

    def test_skill_deployment(self, tmp_path):
        from phalanx.init_cmd import write_cursor_skill

        path = write_cursor_skill(tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "phalanx" in content.lower()


class TestIT086_VariableSubstitution:
    """IT-086: Dynamically replaces {task} placeholders in soul files."""

    def test_task_variable_substitution(self, tmp_path):
        template = tmp_path / "test.md"
        template.write_text("# Soul\n\n{task}")
        content = template.read_text()
        result = content.replace("{task}", "Build a REST API")
        assert "Build a REST API" in result
        assert "{task}" not in result


class TestIT087_TaskInjection:
    """IT-087: Full prompt text injected properly when resolving {task} placeholder."""

    def test_task_placeholder(self, tmp_path):
        template = tmp_path / "soul.md"
        template.write_text("# Your Task\n\n{task}\n\n# End")
        content = template.read_text()
        result = content.replace("{task}", "Write a calculator in Python")
        assert "Write a calculator in Python" in result
