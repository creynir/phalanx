"""Tests for git worktree management — unit tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from phalanx.process.worktree import create_worktree, remove_worktree, list_worktrees


class TestCreateWorktree:
    @patch("phalanx.process.worktree.subprocess.run")
    def test_creates_worktree(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.process.worktree.WORKTREE_BASE", tmp_path / "wt")
        mock_run.return_value = MagicMock(returncode=0)
        repo = Path("/tmp/myrepo")

        path = create_worktree(repo, "agent-1")
        assert "agent-1" in str(path)
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert "worktree" in args[0][0]
        assert "add" in args[0][0]


class TestRemoveWorktree:
    @patch("phalanx.process.worktree.subprocess.run")
    def test_remove_existing(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.process.worktree.WORKTREE_BASE", tmp_path / "wt")
        wt_path = tmp_path / "wt" / "myrepo" / "agent-1"
        wt_path.mkdir(parents=True)
        mock_run.return_value = MagicMock(returncode=0)

        result = remove_worktree(Path("/tmp/myrepo"), "agent-1")
        assert result is True

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.process.worktree.WORKTREE_BASE", tmp_path / "wt")
        result = remove_worktree(Path("/tmp/myrepo"), "nonexistent")
        assert result is False


class TestListWorktrees:
    @patch("phalanx.process.worktree.subprocess.run")
    def test_parse_porcelain(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="worktree /tmp/main\nHEAD abc123\nbranch refs/heads/main\n\n"
                   "worktree /tmp/feat\nHEAD def456\ndetached\n",
        )
        wts = list_worktrees(Path("/tmp/repo"))
        assert len(wts) == 2
        assert wts[0]["path"] == "/tmp/main"
        assert wts[1].get("detached") == "true"

    @patch("phalanx.process.worktree.subprocess.run")
    def test_empty_on_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert list_worktrees(Path("/tmp/repo")) == []
