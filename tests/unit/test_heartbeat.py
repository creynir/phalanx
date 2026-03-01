"""Tests for heartbeat detection."""

from __future__ import annotations

import os
import time
from pathlib import Path

from phalanx.monitor.heartbeat import check_stream_log, is_agent_alive, detect_stall


class TestCheckStreamLog:
    def test_missing_file(self, tmp_path):
        info = check_stream_log(tmp_path / "nonexistent.log")
        assert info["exists"] is False
        assert info["age_seconds"] == float("inf")

    def test_existing_file(self, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("some output")
        info = check_stream_log(log)
        assert info["exists"] is True
        assert info["size"] > 0
        assert info["age_seconds"] < 5


class TestIsAgentAlive:
    def test_alive(self, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("output")
        assert is_agent_alive(log, stall_seconds=180) is True

    def test_missing(self, tmp_path):
        assert is_agent_alive(tmp_path / "missing.log") is False

    def test_stale(self, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("output")
        old_time = time.time() - 300
        os.utime(str(log), (old_time, old_time))
        assert is_agent_alive(log, stall_seconds=180) is False


class TestDetectStall:
    def test_no_stall_fresh_file(self, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("output")
        assert detect_stall(log, stall_seconds=180) is False

    def test_stall_old_file(self, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("output")
        old_time = time.time() - 300
        os.utime(str(log), (old_time, old_time))
        assert detect_stall(log, stall_seconds=180) is True

    def test_no_stall_missing_file(self, tmp_path):
        assert detect_stall(tmp_path / "missing.log") is False

    def test_no_stall_empty_file(self, tmp_path):
        log = tmp_path / "stream.log"
        log.write_text("")
        old_time = time.time() - 300
        os.utime(str(log), (old_time, old_time))
        assert detect_stall(log, stall_seconds=180) is False
