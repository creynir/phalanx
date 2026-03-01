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
    detect_available,
    detect_default,
)
from phalanx.backends.model_router import resolve_model


WS = Path("/tmp/workspace")


class TestCursorBackend:
    def setup_method(self):
        self.b = CursorBackend()

    def test_name(self):
        assert self.b.name == "cursor"

    def test_binary(self):
        assert self.b.binary_name() == "agent"

    def test_supports_worktree(self):
        assert self.b.supports_worktree() is True

    def test_interactive_basic(self):
        cmd = self.b.build_interactive_command("fix bug", WS)
        assert cmd[0] == "agent"
        assert "--workspace" in cmd
        assert "fix bug" in cmd
        assert "--trust" not in cmd

    def test_interactive_with_model_and_worktree(self):
        cmd = self.b.build_interactive_command("task", WS, model="opus-4.6", worktree="feat-x")
        assert "--model" in cmd
        assert "opus-4.6" in cmd
        assert "--worktree" in cmd
        assert "feat-x" in cmd

    def test_headless_basic(self):
        cmd = self.b.build_headless_command("fix tests", WS)
        assert "--print" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--force" in cmd
        assert "fix tests" in cmd

    def test_headless_no_json(self):
        cmd = self.b.build_headless_command("task", WS, json_output=False)
        assert "--output-format" not in cmd

    def test_headless_manual_approve(self):
        cmd = self.b.build_headless_command("task", WS, auto_approve=False)
        assert "--trust" not in cmd
        assert "--force" not in cmd
        assert "--approve-mcps" not in cmd

    def test_resume(self):
        cmd = self.b.build_resume_command("abc-123", message="continue")
        assert "--resume" in cmd
        assert "abc-123" in cmd
        assert "continue" in cmd


class TestClaudeBackend:
    def setup_method(self):
        self.b = ClaudeBackend()

    def test_name(self):
        assert self.b.name == "claude"

    def test_supports_worktree(self):
        assert self.b.supports_worktree() is True

    def test_headless_basic(self):
        cmd = self.b.build_headless_command("refactor auth", WS)
        assert cmd[0] == "claude"
        assert "--print" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "refactor auth" in cmd

    def test_headless_with_model(self):
        cmd = self.b.build_headless_command("task", WS, model="opus")
        assert "--model" in cmd
        assert "opus" in cmd

    def test_resume(self):
        cmd = self.b.build_resume_command("sess-456")
        assert "--resume" in cmd
        assert "sess-456" in cmd


class TestGeminiBackend:
    def setup_method(self):
        self.b = GeminiBackend()

    def test_name(self):
        assert self.b.name == "gemini"

    def test_supports_worktree(self):
        assert self.b.supports_worktree() is False

    def test_headless_basic(self):
        cmd = self.b.build_headless_command("research topic", WS)
        assert cmd[0] == "gemini"
        assert "-p" in cmd
        assert "-o" in cmd
        assert "stream-json" in cmd
        assert "--yolo" in cmd
        assert "research topic" in cmd

    def test_headless_with_policy(self, tmp_path):
        policy = tmp_path / "soul.md"
        policy.write_text("be helpful")
        cmd = self.b.build_headless_command("task", WS, soul_file=policy)
        assert "--policy" in cmd

    def test_resume(self):
        cmd = self.b.build_resume_command("session-7")
        assert "--resume" in cmd
        assert "session-7" in cmd


class TestCodexBackend:
    def setup_method(self):
        self.b = CodexBackend()

    def test_name(self):
        assert self.b.name == "codex"

    def test_supports_worktree(self):
        assert self.b.supports_worktree() is False

    def test_interactive_basic(self):
        cmd = self.b.build_interactive_command("fix bug", WS)
        assert cmd[0] == "codex"
        assert "--full-auto" not in cmd
        assert "--cd" in cmd
        assert str(WS) in cmd

    def test_headless_basic(self):
        cmd = self.b.build_headless_command("write tests", WS)
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "--cd" in cmd
        assert "--sandbox" in cmd
        assert "write tests" in cmd

    def test_resume(self):
        cmd = self.b.build_resume_command("whatever")
        assert "resume" in cmd
        assert "--last" in cmd


class TestRegistry:
    def test_list_backends(self):
        names = list_backends()
        assert set(names) == {"cursor", "claude", "gemini", "codex"}

    def test_get_backend(self):
        b = get_backend("cursor")
        assert isinstance(b, CursorBackend)

    def test_get_unknown(self):
        with pytest.raises(KeyError):
            get_backend("nonexistent")

    def test_detect_available_returns_list(self):
        available = detect_available()
        assert isinstance(available, list)

    def test_detect_default_returns_string(self):
        default = detect_default()
        assert default in list_backends()


class TestModelRouter:
    def test_resolve_known_role(self):
        cfg = {"models": {"cursor": {"coder": "opus-4.6", "default": "gemini-3.1-pro"}}}
        assert resolve_model("cursor", "coder", cfg) == "opus-4.6"

    def test_resolve_falls_back_to_default(self):
        cfg = {"models": {"cursor": {"default": "gemini-3.1-pro"}}}
        assert resolve_model("cursor", "researcher", cfg) == "gemini-3.1-pro"

    def test_resolve_missing_backend_raises(self):
        with pytest.raises(KeyError):
            resolve_model("nonexistent", "coder", {"models": {}})

    def test_all_shipped_backends(self):
        from phalanx.config import load_config
        cfg = load_config()
        for backend_name in ["cursor", "claude", "gemini", "codex"]:
            model = resolve_model(backend_name, "default", cfg)
            assert isinstance(model, str)
            assert len(model) > 0
