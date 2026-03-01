"""Integration tests for phalanx init — IDE detection and skill deployment."""

from __future__ import annotations


import pytest

from phalanx.init_cmd import (
    detect_available_backends,
    init_workspace,
    write_cursor_skill,
    write_claude_skill,
    write_gemini_skill,
    install_global_skill,
    check_and_prompt_skill,
    _skill_is_current,
    _is_workspace,
    _cursor_rule_path,
    _cursor_rule_is_current,
    _ensure_cursor_workspace_rule,
    _GLOBAL_SKILL_PATHS,
)


pytestmark = pytest.mark.integration


class TestDetectBackends:
    def test_detects_installed(self):
        backends = detect_available_backends()
        assert isinstance(backends, list)

    def test_returns_strings(self):
        backends = detect_available_backends()
        for b in backends:
            assert b in ("cursor", "claude", "gemini", "codex")


class TestWriteSkills:
    def test_cursor_skill(self, tmp_path):
        path = write_cursor_skill(tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "phalanx" in content.lower()
        assert ".cursor/rules" in str(path)

    def test_claude_skill(self, tmp_path):
        path = write_claude_skill(tmp_path)
        assert path.exists()
        assert "phalanx" in path.read_text().lower()

    def test_gemini_skill(self, tmp_path):
        path = write_gemini_skill(tmp_path)
        assert path.exists()
        assert "phalanx" in path.read_text().lower()


class TestInitWorkspace:
    def test_creates_phalanx_dir(self, tmp_path):
        (tmp_path / ".cursor").mkdir()
        result = init_workspace(tmp_path)
        assert (tmp_path / ".phalanx").exists()
        assert len(result["skills_created"]) > 0


class TestGlobalSkill:
    def test_install_cursor(self, tmp_path, monkeypatch):
        fake_path = tmp_path / ".cursor" / "skills" / "phalanx" / "SKILL.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "cursor", fake_path)
        path = install_global_skill("cursor")
        assert path.exists()
        assert "phalanx" in path.read_text().lower()

    def test_install_claude_dedicated(self, tmp_path, monkeypatch):
        fake_path = tmp_path / ".claude" / "commands" / "phalanx.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "claude", fake_path)
        install_global_skill("claude")
        assert fake_path.exists()
        assert "phalanx" in fake_path.read_text().lower()

    def test_is_current_after_install(self, tmp_path, monkeypatch):
        fake_path = tmp_path / ".cursor" / "skills" / "phalanx" / "SKILL.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "cursor", fake_path)
        assert not _skill_is_current(fake_path, "cursor")
        install_global_skill("cursor")
        assert _skill_is_current(fake_path, "cursor")


# ── Workspace detection ──────────────────────────────────────


class TestIsWorkspace:
    def test_git_dir_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert _is_workspace(tmp_path) is True

    def test_cursor_dir_detected(self, tmp_path):
        (tmp_path / ".cursor").mkdir()
        assert _is_workspace(tmp_path) is True

    def test_both_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".cursor").mkdir()
        assert _is_workspace(tmp_path) is True

    def test_empty_dir_not_workspace(self, tmp_path):
        assert _is_workspace(tmp_path) is False

    def test_random_files_not_workspace(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")
        assert _is_workspace(tmp_path) is False


# ── Cursor workspace rule ────────────────────────────────────


class TestCursorRulePath:
    def test_returns_mdc_path(self, tmp_path):
        path = _cursor_rule_path(tmp_path)
        assert path == tmp_path / ".cursor" / "rules" / "phalanx.mdc"
        assert str(path).endswith(".mdc")


class TestCursorRuleIsCurrent:
    def test_missing_file_not_current(self, tmp_path):
        assert _cursor_rule_is_current(tmp_path) is False

    def test_matching_content_is_current(self, tmp_path):
        from phalanx.init_cmd import load_skill

        path = _cursor_rule_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(load_skill("cursor"))
        assert _cursor_rule_is_current(tmp_path) is True

    def test_stale_content_not_current(self, tmp_path):
        path = _cursor_rule_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("old content")
        assert _cursor_rule_is_current(tmp_path) is False


class TestEnsureCursorWorkspaceRule:
    def test_creates_rule_in_new_workspace(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        _ensure_cursor_workspace_rule(tmp_path)
        path = _cursor_rule_path(tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "phalanx" in content.lower()
        assert "phalanx" in content.lower()
        captured = capsys.readouterr()
        assert "rule added" in captured.out.lower()

    def test_updates_stale_rule(self, tmp_path, capsys):
        from phalanx.init_cmd import load_skill

        path = _cursor_rule_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("old content")
        _ensure_cursor_workspace_rule(tmp_path)
        assert path.read_text().strip() == load_skill("cursor").strip()
        captured = capsys.readouterr()
        assert "rule updated" in captured.out.lower()

    def test_skips_current_rule(self, tmp_path, capsys):
        from phalanx.init_cmd import load_skill

        path = _cursor_rule_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(load_skill("cursor"))
        _ensure_cursor_workspace_rule(tmp_path)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_creates_parent_dirs(self, tmp_path):
        assert not (tmp_path / ".cursor").exists()
        _ensure_cursor_workspace_rule(tmp_path)
        assert _cursor_rule_path(tmp_path).exists()


# ── check_and_prompt_skill with workspace rule ───────────────


class TestCheckAndPromptSkillCursorRule:
    """Test the cursor workspace rule branch of check_and_prompt_skill."""

    def test_workspace_gets_rule(self, tmp_path, monkeypatch, capsys):
        fake_skill = tmp_path / "global" / "SKILL.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "cursor", fake_skill)
        # Pre-install global skill so it doesn't prompt
        fake_skill.parent.mkdir(parents=True)
        from phalanx.init_cmd import load_skill

        fake_skill.write_text(load_skill("cursor"))

        ws = tmp_path / "project"
        ws.mkdir()
        (ws / ".git").mkdir()

        check_and_prompt_skill("cursor", workspace=ws)
        assert _cursor_rule_path(ws).exists()
        captured = capsys.readouterr()
        assert "rule added" in captured.out.lower()

    def test_non_workspace_shows_warning(self, tmp_path, monkeypatch, capsys):
        fake_skill = tmp_path / "global" / "SKILL.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "cursor", fake_skill)
        fake_skill.parent.mkdir(parents=True)
        from phalanx.init_cmd import load_skill

        fake_skill.write_text(load_skill("cursor"))

        ws = tmp_path / "bare"
        ws.mkdir()

        check_and_prompt_skill("cursor", workspace=ws)
        assert not _cursor_rule_path(ws).exists()
        captured = capsys.readouterr()
        assert "no workspace detected" in captured.out.lower()

    def test_non_cursor_backend_skips_rule(self, tmp_path, monkeypatch, capsys):
        fake_skill = tmp_path / "global" / "phalanx.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "claude", fake_skill)
        fake_skill.parent.mkdir(parents=True)
        from phalanx.init_cmd import load_skill

        fake_skill.write_text(load_skill("claude"))

        ws = tmp_path / "project"
        ws.mkdir()
        (ws / ".git").mkdir()

        check_and_prompt_skill("claude", workspace=ws)
        assert not _cursor_rule_path(ws).exists()
        captured = capsys.readouterr()
        assert "rule" not in captured.out.lower()

    def test_unknown_backend_noop(self, tmp_path, capsys):
        check_and_prompt_skill("nonexistent", workspace=tmp_path)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_global_skill_missing_prompts_then_rule(self, tmp_path, monkeypatch, capsys):
        fake_skill = tmp_path / "global" / "SKILL.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "cursor", fake_skill)

        ws = tmp_path / "project"
        ws.mkdir()
        (ws / ".git").mkdir()

        monkeypatch.setattr("builtins.input", lambda _: "y")
        check_and_prompt_skill("cursor", workspace=ws)

        assert fake_skill.exists()
        assert _cursor_rule_path(ws).exists()
        captured = capsys.readouterr()
        assert "installed" in captured.out.lower()
        assert "rule added" in captured.out.lower()

    def test_global_skill_declined_still_warns_no_workspace(self, tmp_path, monkeypatch, capsys):
        fake_skill = tmp_path / "global" / "SKILL.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "cursor", fake_skill)

        ws = tmp_path / "bare"
        ws.mkdir()

        monkeypatch.setattr("builtins.input", lambda _: "n")
        check_and_prompt_skill("cursor", workspace=ws)

        assert not fake_skill.exists()
        captured = capsys.readouterr()
        assert "skipped" in captured.out.lower()
        assert "no workspace detected" in captured.out.lower()

    def test_outdated_global_skill_auto_updates(self, tmp_path, monkeypatch, capsys):
        fake_skill = tmp_path / "global" / "SKILL.md"
        monkeypatch.setitem(_GLOBAL_SKILL_PATHS, "cursor", fake_skill)
        fake_skill.parent.mkdir(parents=True)
        fake_skill.write_text("old version")

        ws = tmp_path / "project"
        ws.mkdir()
        (ws / ".git").mkdir()

        check_and_prompt_skill("cursor", workspace=ws)

        from phalanx.init_cmd import load_skill

        assert fake_skill.read_text().strip() == load_skill("cursor").strip()
        assert _cursor_rule_path(ws).exists()
        captured = capsys.readouterr()
        assert "skill updated" in captured.out.lower()
        assert "rule added" in captured.out.lower()
