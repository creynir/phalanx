"""Global pytest configuration and fixtures."""

import os
import pytest


@pytest.fixture(autouse=True)
def disable_cursor_spawn_delay():
    """Suppress the Cursor backend's inter-spawn stagger in all tests.

    In production, the Cursor backend sleeps 3 s between spawns to avoid a
    cli-config.json race. In tests we never launch real Cursor processes, so
    the delay just makes the suite slow.
    """
    os.environ["PHALANX_CURSOR_SPAWN_DELAY"] = "0"
    yield
    os.environ.pop("PHALANX_CURSOR_SPAWN_DELAY", None)
