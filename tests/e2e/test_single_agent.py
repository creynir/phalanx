"""E2E test: single agent mode via phalanx run (v2)."""

from __future__ import annotations

import subprocess

import pytest

from phalanx import __version__


pytestmark = pytest.mark.e2e


class TestSingleAgent:
    def test_phalanx_version(self):
        result = subprocess.run(
            ["phalanx", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert __version__ in result.stdout

    def test_phalanx_help(self):
        result = subprocess.run(
            ["phalanx", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        # v2: groups are listed
        assert "team" in result.stdout
        assert "agent" in result.stdout

    def test_phalanx_status(self):
        result = subprocess.run(
            ["phalanx", "--root", "/tmp/phalanx-e2e-test", "team", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_phalanx_list_teams(self):
        result = subprocess.run(
            ["phalanx", "--json-output", "--root", "/tmp/phalanx-e2e-test", "team", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
