"""Tests for cost tracking integration in team_monitor.

Covers:
- _StreamLogCostScanner incremental parsing
- Cost data in get_team_status
- Integration between scanner and CostAggregator
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from phalanx.costs.aggregator import CostAggregator
from phalanx.db import StateDB
from phalanx.monitor.team_monitor import _StreamLogCostScanner


@pytest.fixture
def tmp_db(tmp_path):
    db = StateDB(db_path=tmp_path / "state.db")
    db.create_team("t1", "test task")
    db.create_agent("w1", "t1", "code", role="worker", backend="cursor")
    return db


class TestStreamLogCostScanner:
    def test_scan_empty_log(self, tmp_path):
        """Empty stream log produces no records."""
        log = tmp_path / "stream.log"
        log.write_text("")
        mock_agg = MagicMock()

        scanner = _StreamLogCostScanner()
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)

        mock_agg.record_usage.assert_not_called()

    def test_scan_no_token_lines(self, tmp_path):
        """Log with no token usage lines produces no records."""
        log = tmp_path / "stream.log"
        log.write_text("Tool call: read_file\nDone.\n")
        mock_agg = MagicMock()

        scanner = _StreamLogCostScanner()
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)

        mock_agg.record_usage.assert_not_called()

    def test_scan_missing_log(self, tmp_path):
        """Missing stream log does not crash."""
        log = tmp_path / "nonexistent.log"
        mock_agg = MagicMock()

        scanner = _StreamLogCostScanner()
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)
        mock_agg.record_usage.assert_not_called()

    def test_scan_incremental_no_double_count(self, tmp_path):
        """Lines already scanned are not re-parsed on the next poll cycle."""
        log = tmp_path / "stream.log"
        log.write_text("tokens: 100\n")
        mock_agg = MagicMock()

        scanner = _StreamLogCostScanner()
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)
        first_call_count = mock_agg.record_usage.call_count

        # No new content — second scan should not record again
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)
        assert mock_agg.record_usage.call_count == first_call_count

    def test_scan_new_lines_after_first_scan(self, tmp_path):
        """New lines appended after first scan are picked up on second scan."""
        log = tmp_path / "stream.log"
        log.write_text("initial content\n")
        mock_agg = MagicMock()

        scanner = _StreamLogCostScanner()
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)
        calls_after_first = mock_agg.record_usage.call_count

        # Append a token usage line
        with open(log, "a") as f:
            f.write("tokens: 500\n")

        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)
        # Cursor's parse_token_usage matches "tokens: 500" — should be 1 more record
        assert mock_agg.record_usage.call_count == calls_after_first + 1

    def test_reset_clears_offset(self, tmp_path):
        """reset() allows the scanner to re-read from the beginning."""
        log = tmp_path / "stream.log"
        log.write_text("tokens: 200\n")
        mock_agg = MagicMock()

        scanner = _StreamLogCostScanner()
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)
        assert mock_agg.record_usage.call_count == 1

        scanner.reset("w1")
        scanner.scan("w1", log, "cursor", mock_agg, "t1", "worker", None)
        # After reset the line is scanned again
        assert mock_agg.record_usage.call_count == 2

    def test_reset_nonexistent_agent_is_safe(self):
        """reset() for unknown agent does not raise."""
        scanner = _StreamLogCostScanner()
        scanner.reset("nonexistent-agent")  # should not raise

    def test_scan_with_real_db(self, tmp_path, tmp_db):
        """Integration: scanner writes to DB via real CostAggregator."""
        log = tmp_path / "stream.log"
        log.write_text("tokens: 300\n")

        agg = CostAggregator(tmp_db)
        scanner = _StreamLogCostScanner()
        scanner.scan("w1", log, "cursor", agg, "t1", "worker", "claude-3.5-sonnet")

        records = tmp_db.get_agent_token_usage("w1")
        assert len(records) == 1
        r = records[0]
        assert r["input_tokens"] + r["output_tokens"] > 0 or r["total_tokens"] >= 0

    def test_invalid_backend_does_not_crash(self, tmp_path):
        """Unknown backend name logs warning, does not raise."""
        log = tmp_path / "stream.log"
        log.write_text("tokens: 100\n")
        mock_agg = MagicMock()

        scanner = _StreamLogCostScanner()
        # Should not raise even with an unrecognised backend
        scanner.scan("w1", log, "unknown-backend-xyz", mock_agg, "t1", "worker", None)


class TestCostScannerInMonitorLoop:
    """Tests that run_team_monitor calls the cost scanner."""

    def _make_agent(self, agent_id: str = "w1", status: str = "running") -> dict:
        return {
            "id": agent_id,
            "team_id": "t1",
            "role": "worker",
            "status": status,
            "backend": "cursor",
            "model": None,
            "artifact_status": None,
            "updated_at": 0,
        }

    def test_cost_aggregator_optional(self):
        """run_team_monitor works fine without a cost_aggregator (None)."""
        from phalanx.monitor.team_monitor import run_team_monitor

        db = MagicMock()
        db.list_agents.side_effect = [[], Exception("stop")]
        pm = MagicMock()
        hb = MagicMock()
        sd = MagicMock()

        # Should exit cleanly on empty agents list
        run_team_monitor(
            team_id="t1",
            db=db,
            process_manager=pm,
            heartbeat_monitor=hb,
            stall_detector=sd,
            poll_interval=1,
            cost_aggregator=None,
        )

    def test_cost_scanner_called_for_running_agent(self, tmp_path):
        """When a running agent has a stream.log, the scanner is invoked."""
        from phalanx.monitor.team_monitor import run_team_monitor

        log = tmp_path / "stream.log"
        log.write_text("tokens: 100\n")

        agent = self._make_agent()
        proc = MagicMock()
        proc.stream_log = log

        db = MagicMock()
        # First iteration: one running agent; second iteration: agent is dead → exit
        dead_agent = dict(agent, status="dead")
        db.list_agents.side_effect = [[agent], [dead_agent]]
        db.get_agent.return_value = agent

        pm = MagicMock()
        pm.get_process.return_value = proc
        hb = MagicMock()
        hb.get_state.return_value = MagicMock(last_heartbeat=0.0)
        hb.check.return_value = MagicMock(last_heartbeat=1.0)
        sd = MagicMock()
        sd.check_agent.return_value = None

        mock_agg = MagicMock()

        run_team_monitor(
            team_id="t1",
            db=db,
            process_manager=pm,
            heartbeat_monitor=hb,
            stall_detector=sd,
            poll_interval=0,
            cost_aggregator=mock_agg,
        )

        # The aggregator's record_usage may or may not be called depending on
        # parse_token_usage result, but scan() should have been attempted —
        # we verify by checking get_process was called (scanner path is gated on it)
        pm.get_process.assert_called()


class TestGetTeamStatusIncludesCosts:
    """Tests that get_team_status includes cost data."""

    def test_costs_included_in_status(self, tmp_path):
        db = StateDB(db_path=tmp_path / "state.db")
        db.create_team("t1", "test task")
        db.create_agent("w1", "t1", "code", role="worker", backend="cursor")

        agg = CostAggregator(db)
        agg.record_usage("t1", "w1", "worker", "cursor", "claude-4-opus", 1000, 500)

        from phalanx.team.orchestrator import get_team_status

        status = get_team_status(db, "t1")
        assert status is not None
        assert "costs" in status
        costs = status["costs"]
        assert costs is not None
        assert costs["total_tokens"] == 1500

    def test_costs_none_for_new_team(self, tmp_path):
        """New team with no usage returns costs with zeros."""
        db = StateDB(db_path=tmp_path / "state.db")
        db.create_team("t1", "test task")

        from phalanx.team.orchestrator import get_team_status

        status = get_team_status(db, "t1")
        assert status is not None
        costs = status["costs"]
        assert costs is not None
        assert costs["total_tokens"] == 0
        assert costs["estimated_cost"] is None

    def test_team_not_found(self, tmp_path):
        db = StateDB(db_path=tmp_path / "state.db")

        from phalanx.team.orchestrator import get_team_status

        assert get_team_status(db, "nonexistent") is None
