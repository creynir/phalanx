"""Tests for CLI package dependencies."""

from __future__ import annotations


def test_fastapi_import():
    """Test that fastapi can be imported successfully."""
    import fastapi  # noqa: F401


def test_uvicorn_import():
    """Test that uvicorn can be imported successfully."""
    import uvicorn  # noqa: F401
