"""Tests for soul file loader — skill generation, cursor rule, frontmatter."""

from __future__ import annotations

import pytest

from phalanx.soul.loader import (
    load_skill,
    load_cursor_rule,
    _FRONTMATTER,
    _CURSOR_RULE_FRONTMATTER,
    _load_skill_body,
)


class TestLoadSkillBody:
    def test_returns_nonempty_string(self):
        body = _load_skill_body()
        assert isinstance(body, str)
        assert len(body) > 100

    def test_contains_phalanx(self):
        body = _load_skill_body()
        assert "phalanx" in body.lower()


class TestLoadSkill:
    def test_default_uses_cursor_frontmatter(self):
        content = load_skill()
        assert "phalanx-orchestration" in content

    @pytest.mark.parametrize("backend", ["cursor", "claude", "gemini", "codex"])
    def test_each_backend_has_frontmatter(self, backend):
        content = load_skill(backend)
        assert content.startswith("---")
        assert "---\n" in content[4:]
        assert "phalanx" in content.lower()

    def test_cursor_has_description_keywords(self):
        content = load_skill("cursor")
        assert "multi-agent" in content
        assert "sub-agents" in content
        assert "delegating tasks" in content

    def test_claude_has_use_when(self):
        content = load_skill("claude")
        assert "Use when" in content

    def test_gemini_has_use_when(self):
        content = load_skill("gemini")
        assert "Use when" in content

    def test_codex_has_metadata(self):
        content = load_skill("codex")
        assert "metadata:" in content

    def test_unknown_backend_falls_back_to_cursor(self):
        content = load_skill("unknown_backend")
        cursor_content = load_skill("cursor")
        assert content == cursor_content

    def test_none_backend_uses_cursor(self):
        content = load_skill(None)
        cursor_content = load_skill("cursor")
        assert content == cursor_content

    def test_skill_body_appended(self):
        for backend in ["cursor", "claude", "gemini", "codex"]:
            content = load_skill(backend)
            assert "create-team" in content
            assert "team-status" in content


class TestLoadCursorRule:
    def test_returns_string(self):
        content = load_cursor_rule()
        assert isinstance(content, str)

    def test_has_always_apply(self):
        content = load_cursor_rule()
        assert "alwaysApply: true" in content

    def test_has_description(self):
        content = load_cursor_rule()
        assert "description:" in content

    def test_does_not_have_name(self):
        assert "name:" not in _CURSOR_RULE_FRONTMATTER

    def test_has_skill_body(self):
        content = load_cursor_rule()
        assert "create-team" in content
        assert "team-status" in content

    def test_differs_from_skill(self):
        rule = load_cursor_rule()
        skill = load_skill("cursor")
        assert rule != skill
        assert "alwaysApply: true" in rule
        assert "alwaysApply: true" not in skill


class TestFrontmatterIntegrity:
    @pytest.mark.parametrize("backend", ["cursor", "claude", "gemini", "codex"])
    def test_frontmatter_starts_and_ends_with_delimiters(self, backend):
        fm = _FRONTMATTER[backend]
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")

    def test_cursor_rule_frontmatter_delimiters(self):
        assert _CURSOR_RULE_FRONTMATTER.startswith("---\n")
        assert _CURSOR_RULE_FRONTMATTER.endswith("---\n")
