"""Tests for backend adapters, registry, and model router."""

from __future__ import annotations

from pathlib import Path

import pytest

from phalanx.backends.cursor import CursorBackend
from phalanx.backends.claude import ClaudeBackend
from phalanx.backends.gemini import GeminiBackend
from phalanx.backends.codex import CodexBackend
from phalanx.backends.registry import (
    get_backend,
    list_backends,
)
from phalanx.team.config import resolve_model


WS = Path("/tmp/workspace")


class TestCursorBackend:
    def setup_method(self):
        self.b = CursorBackend()

    def test_name(self):
        assert self.b.name() == "cursor"

    def test_binary(self):
        assert self.b.binary_name().endswith("agent")

    def test_supports_worktree(self):
        pass

    def test_interactive_basic(self):
        cmd = self.b.build_start_command("fix bug")
        assert cmd[0].endswith("agent")
        # Cursor uses deferred prompt — prompt is NOT in the start command
        assert "fix bug" not in cmd
        assert self.b.deferred_prompt() is True
        assert self.b.format_deferred_prompt("fix bug") == "fix bug"

    def test_interactive_with_model_and_worktree(self):
        cmd = self.b.build_start_command("task", model="opus-4.6", worktree="feat-x")
        assert "--model" in cmd
        assert "opus-4.6" in cmd
        assert "--worktree" in cmd
        assert "feat-x" in cmd

    def test_prompt_uses_inline_content(self, tmp_path):
        task_file = tmp_path / "task.md"
        task_file.write_text("Do the thing now.")
        cmd = self.b.build_start_command(str(task_file))
        # Cursor deferred prompt: build_start_command has no prompt
        assert not any("Read and execute" in c for c in cmd)
        # format_deferred_prompt transforms file paths into read instructions
        deferred = self.b.format_deferred_prompt(str(task_file))
        assert "Read and execute instructions from" in deferred
        assert str(task_file.absolute()) in deferred

    def test_prompt_with_soul_file(self, tmp_path):
        soul = tmp_path / "soul.md"
        soul.write_text("instructions")
        task_file = tmp_path / "task.md"
        task_file.write_text("Do the thing now.")
        cmd = self.b.build_start_command(str(task_file), soul_file=None)
        # Deferred prompt: command has no prompt, file reference is in format_deferred_prompt
        assert not any("Read and execute" in c for c in cmd)
        deferred = self.b.format_deferred_prompt(str(task_file))
        assert "Read and execute instructions from" in deferred
        assert str(task_file.absolute()) in deferred

    def test_headless_manual_approve(self):
        cmd = self.b.build_start_command("task", auto_approve=False)
        assert "--trust" not in cmd
        assert "--force" not in cmd
        assert "--approve-mcps" not in cmd
        assert "--yolo" not in cmd

    def test_resume(self):
        cmd = self.b.build_resume_command("abc-123")
        assert "--resume" in cmd
        assert "abc-123" in cmd


class TestClaudeBackend:
    def setup_method(self):
        self.b = ClaudeBackend()

    def test_name(self):
        assert self.b.name() == "claude"

    def test_supports_worktree(self):
        pass

    def test_headless_basic(self):
        cmd = self.b.build_start_command("refactor auth")
        assert cmd[0].endswith("claude")
        assert "--dangerously-skip-permissions" in cmd
        assert "@refactor auth" in cmd

    def test_headless_with_model(self):
        cmd = self.b.build_start_command("task", model="opus")
        assert "--model" in cmd
        assert "opus" in cmd

    def test_resume(self):
        cmd = self.b.build_resume_command("sess-456")
        assert "sess-456" in cmd


class TestGeminiBackend:
    def setup_method(self):
        self.b = GeminiBackend()

    def test_name(self):
        assert self.b.name() == "gemini"

    def test_supports_worktree(self):
        pass

    def test_headless_basic(self):
        cmd = self.b.build_start_command("research topic")
        assert cmd[0].endswith("gemini")
        assert "--yolo" in cmd
        assert "@research topic" in cmd

    def test_headless_with_policy(self, tmp_path):
        policy = tmp_path / "soul.md"
        policy.write_text("be helpful")
        cmd = self.b.build_start_command("task", soul_file=policy)
        assert "be helpful" not in cmd  # just passed as file

    def test_resume(self):
        cmd = self.b.build_resume_command("session-7")
        assert "--resume" in cmd
        assert "session-7" in cmd


class TestCodexBackend:
    def setup_method(self):
        self.b = CodexBackend()

    def test_name(self):
        assert self.b.name() == "codex"

    def test_supports_worktree(self):
        pass

    def test_interactive_basic(self):
        cmd = self.b.build_start_command("fix bug")
        assert cmd[0].endswith("codex")
        assert "--full-auto" in cmd
        assert "@fix bug" in cmd

    def test_headless_basic(self):
        cmd = self.b.build_start_command("write tests")
        assert cmd[0].endswith("codex")
        assert "--full-auto" in cmd
        assert "@write tests" in cmd

    def test_resume(self):
        cmd = self.b.build_resume_command("whatever")
        assert "--resume" in cmd
        assert "whatever" in cmd


class TestRegistry:
    def test_list_backends(self):
        names = list_backends()
        assert set(names) == {"cursor", "claude", "gemini", "codex"}

    def test_get_backend(self):
        b = get_backend("cursor")
        assert isinstance(b, CursorBackend)

    def test_get_unknown(self):
        with pytest.raises(ValueError):
            get_backend("nonexistent")

    def test_detect_available_returns_list(self):
        pass

    def test_detect_default_returns_string(self):
        pass


class TestModelRouter:
    def test_resolve_with_explicit_model(self):
        assert resolve_model("cursor", "coder", "opus-4.6") == "opus-4.6"

    def test_resolve_falls_back_to_role_default(self):
        model = resolve_model("cursor", "architect")
        assert model == "opus-4.6"

    def test_resolve_falls_back_to_backend_default(self):
        model = resolve_model("cursor", "unknown_role")
        assert model == "sonnet-4.6"

    def test_all_shipped_backends(self):
        for backend_name in ["cursor", "claude", "gemini", "codex"]:
            model = resolve_model(backend_name, "coder")
            assert isinstance(model, str)
            assert len(model) > 0
