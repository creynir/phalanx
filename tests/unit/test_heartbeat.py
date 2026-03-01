"""Tests for heartbeat detection."""

from __future__ import annotations

import time
from pathlib import Path

from phalanx.monitor.heartbeat import HeartbeatMonitor


class TestHeartbeatMonitor:
    def test_register_and_check_new_file(self, tmp_path: Path):
        monitor = HeartbeatMonitor(idle_timeout=60)
        log_path = tmp_path / "stream.log"
        log_path.write_text("initial output")

        monitor.register("agent-1", log_path)
        state = monitor.get_state("agent-1")
        assert state is not None
        assert state.agent_id == "agent-1"
        assert not state.is_stale()

        # Check updates last_mtime, last_size, last_tail_hash
        updated_state = monitor.check("agent-1")
        assert updated_state is not None
        assert updated_state.last_size > 0
        assert updated_state.last_tail_hash != ""

    def test_check_missing_file(self, tmp_path: Path):
        monitor = HeartbeatMonitor(idle_timeout=60)
        log_path = tmp_path / "missing.log"

        monitor.register("agent-1", log_path)
        state = monitor.check("agent-1")
        # Should not error, just returns current state without updating mtime
        assert state is not None
        assert state.last_size == 0

    def test_detect_stale(self, tmp_path: Path):
        monitor = HeartbeatMonitor(idle_timeout=1)  # Very short timeout
        log_path = tmp_path / "stream.log"
        log_path.write_text("initial")

        monitor.register("agent-1", log_path)
        monitor.check("agent-1")

        # Manually backdate the heartbeat to force stale
        state = monitor.get_state("agent-1")
        state.last_heartbeat = time.time() - 5

        assert state.is_stale()
        assert "agent-1" in monitor.get_stale_agents()

    def test_file_updates_prevent_stale(self, tmp_path: Path):
        monitor = HeartbeatMonitor(idle_timeout=1)
        log_path = tmp_path / "stream.log"
        log_path.write_text("initial")

        monitor.register("agent-1", log_path)
        monitor.check("agent-1")

        state = monitor.get_state("agent-1")
        state.last_heartbeat = time.time() - 5

        # Modify file
        log_path.write_text("initial\nmore output")

        # Check should see modification and update heartbeat
        monitor.check("agent-1")
        assert not state.is_stale()
        assert "agent-1" not in monitor.get_stale_agents()

    def test_unregister(self, tmp_path: Path):
        monitor = HeartbeatMonitor()
        monitor.register("a1", tmp_path / "log")
        assert monitor.get_state("a1") is not None

        monitor.unregister("a1")
        assert monitor.get_state("a1") is None
        assert monitor.check("a1") is None

    def test_check_all(self, tmp_path: Path):
        monitor = HeartbeatMonitor()
        monitor.register("a1", tmp_path / "log1")
        monitor.register("a2", tmp_path / "log2")

        (tmp_path / "log1").write_text("1")
        (tmp_path / "log2").write_text("2")

        results = monitor.check_all()
        assert "a1" in results
        assert "a2" in results
        assert results["a1"].last_size > 0
        assert results["a2"].last_size > 0
