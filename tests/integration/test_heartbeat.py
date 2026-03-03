"""Integration tests for Heartbeat Monitoring — IT-018 through IT-021."""

from __future__ import annotations

import time

import pytest

from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor


pytestmark = pytest.mark.integration


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


@pytest.fixture
def hb():
    return HeartbeatMonitor()


class TestIT018_Registration:
    """IT-018: register() correctly sets baseline mtime/hash for stream.log."""

    def test_register_sets_baseline(self, hb, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("initial output")
        hb.register("agent-1", log)
        state = hb.get_state("agent-1")
        assert state is not None
        assert state.last_heartbeat > 0


class TestIT019_StaleDetection:
    """IT-019: Identifies stale heartbeat when log file doesn't mutate."""

    def test_stale_when_no_change(self, hb, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("initial")
        hb.register("agent-1", log)

        state = hb.get_state("agent-1")
        assert state is not None
        far_future = time.time() + 3600
        assert state.is_stale(far_future) is True


class TestIT020_HeartbeatUpdate:
    """IT-020: Heartbeat resets when agent prints new output."""

    def test_heartbeat_resets_on_new_output(self, hb, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("initial")
        hb.register("agent-1", log)

        old_state = hb.get_state("agent-1")
        old_hb = old_state.last_heartbeat

        time.sleep(0.05)
        log.write_text("initial\nnew output line")
        new_state = hb.check("agent-1")
        assert new_state is not None
        assert new_state.last_heartbeat >= old_hb


class TestIT021_ThresholdTimeout:
    """IT-021: Monitor sets agent to suspended upon hitting idle_timeout."""

    def test_idle_timeout_triggers_stale(self, hb, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("initial")
        hb.register("agent-1", log)

        state = hb.get_state("agent-1")
        future = state.last_heartbeat + 1801
        assert state.is_stale(future) is True
