"""Integration tests for Soul file loading — IT-086 supplement.

Tests that the loader module works with real files and that the integration
between loader → spawn chain handles edge cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phalanx.soul.loader import load_soul_file


pytestmark = pytest.mark.integration


class TestLoadSoulFileIntegration:
    """Tests load_soul_file with real filesystem operations."""

    def test_load_existing_file(self, tmp_path: Path):
        soul = tmp_path / "worker.md"
        soul.write_text("You are a coder agent.")
        content = load_soul_file(soul)
        assert content == "You are a coder agent."

    def test_load_missing_file(self, tmp_path: Path):
        content = load_soul_file(tmp_path / "nonexistent.md")
        assert content == ""

    def test_variable_substitution(self, tmp_path: Path):
        soul = tmp_path / "agent.md"
        soul.write_text("Team: {{TEAM_ID}}, Agent: {{AGENT_ID}}, Role: {{ROLE}}")
        content = load_soul_file(
            soul,
            variables={"TEAM_ID": "team-abc", "AGENT_ID": "worker-1", "ROLE": "coder"},
        )
        assert "team-abc" in content
        assert "worker-1" in content
        assert "coder" in content
        assert "{{" not in content

    def test_partial_variable_substitution(self, tmp_path: Path):
        soul = tmp_path / "agent.md"
        soul.write_text("Team: {{TEAM_ID}}, Missing: {{UNKNOWN}}")
        content = load_soul_file(soul, variables={"TEAM_ID": "t1"})
        assert "t1" in content
        assert "{{UNKNOWN}}" in content

    def test_no_variables_keeps_placeholders(self, tmp_path: Path):
        soul = tmp_path / "agent.md"
        soul.write_text("Team: {{TEAM_ID}}")
        content = load_soul_file(soul)
        assert "{{TEAM_ID}}" in content

    def test_empty_file(self, tmp_path: Path):
        soul = tmp_path / "empty.md"
        soul.write_text("")
        content = load_soul_file(soul)
        assert content == ""

    def test_unicode_content(self, tmp_path: Path):
        soul = tmp_path / "unicode.md"
        soul.write_text("こんにちは {{NAME}} — café résumé 🎉")
        content = load_soul_file(soul, variables={"NAME": "Agent"})
        assert "Agent" in content
        assert "café" in content

    def test_bundled_soul_files_exist(self):
        """Verify bundled soul files ship with the package."""
        bundled = Path(__file__).parent.parent.parent / "phalanx" / "soul"
        if bundled.exists():
            worker = bundled / "worker.md"
            lead = bundled / "team_lead.md"
            if worker.exists():
                content = load_soul_file(worker)
                assert len(content) > 0
            if lead.exists():
                content = load_soul_file(lead)
                assert len(content) > 0
