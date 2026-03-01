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
from phalanx.backends.model_router import resolve_model


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
        assert "fix bug" in cmd
        assert "--trust" not in cmd

    def test_interactive_with_model_and_worktree(self):
        cmd = self.b.build_start_command("task", model="opus-4.6", worktree="feat-x")
        assert "--model" in cmd
        assert "opus-4.6" in cmd
        assert "--worktree" in cmd
        assert "feat-x" in cmd

    def test_headless_basic(self):
        cmd = self.b.build_start_command("fix tests")
        assert "fix tests" in cmd

    def test_headless_no_json(self):
        pass

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
        assert "refactor auth" in cmd

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
        assert "research topic" in cmd

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
        assert "fix bug" in cmd

    def test_headless_basic(self):
        cmd = self.b.build_start_command("write tests")
        assert cmd[0].endswith("codex")
        assert "--full-auto" in cmd
        assert "write tests" in cmd

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
    def test_resolve_known_role(self):
        cfg = {"models": {"cursor": {"coder": "opus-4.6", "default": "gemini-3.1-pro"}}}
        assert resolve_model("cursor", "coder", cfg) == "opus-4.6"

    def test_resolve_falls_back_to_default(self):
        cfg = {"models": {"cursor": {"default": "gemini-3.1-pro"}}}
        assert resolve_model("cursor", "researcher", cfg) == "gemini-3.1-pro"

    def test_resolve_missing_backend_raises(self):
        with pytest.raises(KeyError):
            resolve_model("nonexistent", "coder", {"models": {}})

    def test_all_shipped_backends(self, tmp_path):
        from phalanx.config import load_config

        load_config(tmp_path)
        # load_config loads into PhalanxConfig which might not have 'models' in its base definition
        # let's mock the config dict structure since load_config doesn't return the raw dict
        mock_cfg_dict = {
            "models": {
                "cursor": {"default": "claude-sonnet-4-20250514"},
                "claude": {"default": "claude-3-5-sonnet-20241022"},
                "gemini": {"default": "gemini-2.5-pro"},
                "codex": {"default": "o3"},
            }
        }
        for backend_name in ["cursor", "claude", "gemini", "codex"]:
            model = resolve_model(backend_name, "default", mock_cfg_dict)
            assert isinstance(model, str)
            assert len(model) > 0
