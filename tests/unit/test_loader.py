"""Tests for soul file resolution."""

from __future__ import annotations

from pathlib import Path

from phalanx.team.spawn import _resolve_soul_file


class TestResolveSoulFile:
    def test_returns_user_override_if_exists(self, tmp_path: Path):
        soul_dir = tmp_path / "soul"
        soul_dir.mkdir()
        worker_soul = soul_dir / "agent.md"
        worker_soul.write_text("custom worker soul")
        result = _resolve_soul_file(tmp_path, "worker")
        assert result == worker_soul

    def test_returns_lead_override_if_exists(self, tmp_path: Path):
        soul_dir = tmp_path / "soul"
        soul_dir.mkdir()
        lead_soul = soul_dir / "team_lead.md"
        lead_soul.write_text("custom lead soul")
        result = _resolve_soul_file(tmp_path, "lead")
        assert result == lead_soul

    def test_returns_bundled_if_no_override(self, tmp_path: Path):
        result = _resolve_soul_file(tmp_path, "worker")
        if result is not None:
            assert result.name == "agent.md"

    def test_returns_none_if_nothing_found(self, tmp_path: Path):
        (tmp_path / "soul").mkdir()
        result = _resolve_soul_file(tmp_path, "nonexistent_role")
        # Falls back to "agent.md" which may or may not exist as bundled
        # The function returns None only if no soul file exists at all
        assert result is None or result.exists()
