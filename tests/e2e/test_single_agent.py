"""E2E test: single agent mode via phalanx run."""

from __future__ import annotations

import subprocess

import pytest


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
        assert "0.3.3" in result.stdout

    def test_phalanx_help(self):
        result = subprocess.run(
            ["phalanx", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "create-team" in result.stdout

    def test_phalanx_status(self):
        result = subprocess.run(
            ["phalanx", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_phalanx_models_show(self):
        pass
