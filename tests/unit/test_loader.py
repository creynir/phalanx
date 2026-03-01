"""Tests for soul file loader and dynamic variable injection."""

from __future__ import annotations

from pathlib import Path

from phalanx.soul.loader import load_soul_file


class TestLoadSoulFile:
    def test_load_existing_file(self, tmp_path: Path):
        soul = tmp_path / "agent.md"
        soul.write_text("Hello, I am an agent.")
        content = load_soul_file(soul)
        assert content == "Hello, I am an agent."

    def test_load_missing_file(self, tmp_path: Path):
        content = load_soul_file(tmp_path / "missing.md")
        assert content == ""

    def test_load_with_variables(self, tmp_path: Path):
        soul = tmp_path / "agent.md"
        soul.write_text("Team: {{TEAM_ID}}, Agent: {{AGENT_ID}}")
        content = load_soul_file(soul, variables={"TEAM_ID": "team-123", "AGENT_ID": "agent-456"})
        assert content == "Team: team-123, Agent: agent-456"

    def test_load_missing_variables_left_intact(self, tmp_path: Path):
        soul = tmp_path / "agent.md"
        soul.write_text("Team: {{TEAM_ID}}, Role: {{ROLE}}")
        content = load_soul_file(soul, variables={"TEAM_ID": "team-123"})
        assert content == "Team: team-123, Role: {{ROLE}}"

    def test_load_no_variables_dict(self, tmp_path: Path):
        soul = tmp_path / "agent.md"
        soul.write_text("Hello {{TEAM_ID}}")
        content = load_soul_file(soul)
        assert content == "Hello {{TEAM_ID}}"
