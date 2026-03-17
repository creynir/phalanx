"""RED-team tests for Phase 4: Eager chat_id persistence via _ChatIdScanner.

All tests in this file are expected to FAIL before the _ChatIdScanner class
and its integration into the monitor poll loop are implemented.

ADR-001 Phase 4 coverage:
  - Claude session ID extracted from stream.log JSON
  - Cursor chat_id extracted from stream.log
  - No chat_id in output -> None returned
  - Duplicate chat_id not rewritten
  - Incremental reads (offset tracking)
  - chat_id persisted before agent death in same poll cycle
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from phalanx.monitor.team_monitor import run_team_monitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deps(agents=None):
    """Return a minimal set of mocked collaborators for run_team_monitor."""
    db = MagicMock()
    pm = MagicMock()
    hm = MagicMock()
    sd = MagicMock()

    pm.get_process.return_value = None
    pm.consume_startup_blocked.return_value = None
    pm.discover_agent.return_value = None
    hm.get_state.return_value = None
    hm.check.return_value = None
    sd.check_agent.return_value = None

    if agents is None:
        agents = []
    db.list_agents.side_effect = [agents, []]

    return db, pm, hm, sd


def _run_one_tick(db, pm, hm, sd, **kwargs):
    """Run run_team_monitor for exactly one meaningful tick then let it exit."""
    run_team_monitor(
        team_id="team-1",
        db=db,
        process_manager=pm,
        heartbeat_monitor=hm,
        stall_detector=sd,
        poll_interval=0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Claude chat_id extracted from stream.log
# ---------------------------------------------------------------------------

def test_claude_chat_id_extracted_from_stream_log(tmp_path):
    """When stream.log contains a Claude JSON line with sessionId,
    the _ChatIdScanner must parse it and return the session ID."""
    from phalanx.monitor.team_monitor import _ChatIdScanner
    from phalanx.backends.claude import ClaudeBackend

    stream_log = tmp_path / "stream.log"
    stream_log.write_text('{"sessionId": "sess-abc123"}\n')

    scanner = _ChatIdScanner()
    backend = ClaudeBackend()
    result = scanner.scan("agent-1", stream_log, backend)

    assert result == "sess-abc123"


# ---------------------------------------------------------------------------
# 2. Cursor chat_id extracted from stream.log
# ---------------------------------------------------------------------------

def test_cursor_chat_id_extracted(tmp_path):
    """When stream.log contains a Cursor-format chat_id line,
    the scanner must return the parsed chat_id."""
    from phalanx.monitor.team_monitor import _ChatIdScanner
    from phalanx.backends.cursor import CursorBackend

    stream_log = tmp_path / "stream.log"
    stream_log.write_text("chat_id: 'cursor-xyz789'\n")

    scanner = _ChatIdScanner()
    backend = CursorBackend()
    result = scanner.scan("agent-1", stream_log, backend)

    assert result == "cursor-xyz789"


# ---------------------------------------------------------------------------
# 3. No chat_id in output -> None
# ---------------------------------------------------------------------------

def test_no_chat_id_no_result(tmp_path):
    """When stream.log contains only regular output with no chat_id pattern,
    the scanner must return None."""
    from phalanx.monitor.team_monitor import _ChatIdScanner
    from phalanx.backends.claude import ClaudeBackend

    stream_log = tmp_path / "stream.log"
    stream_log.write_text("Running tests...\nAll tests passed.\n")

    scanner = _ChatIdScanner()
    backend = ClaudeBackend()
    result = scanner.scan("agent-1", stream_log, backend)

    assert result is None


# ---------------------------------------------------------------------------
# 4. Duplicate chat_id not returned
# ---------------------------------------------------------------------------

def test_duplicate_chat_id_not_returned(tmp_path):
    """When the scanner finds a chat_id that matches the known_chat_id,
    it must return None to avoid unnecessary DB writes."""
    from phalanx.monitor.team_monitor import _ChatIdScanner
    from phalanx.backends.claude import ClaudeBackend

    stream_log = tmp_path / "stream.log"
    stream_log.write_text('{"sessionId": "abc123"}\n')

    scanner = _ChatIdScanner()
    backend = ClaudeBackend()
    result = scanner.scan("agent-1", stream_log, backend, known_chat_id="abc123")

    assert result is None


# ---------------------------------------------------------------------------
# 5. Incremental reads — offset tracking
# ---------------------------------------------------------------------------

def test_incremental_reads_correct(tmp_path):
    """First scan reads initial content (no chat_id), second scan reads only
    the newly appended bytes and finds the chat_id."""
    from phalanx.monitor.team_monitor import _ChatIdScanner
    from phalanx.backends.claude import ClaudeBackend

    stream_log = tmp_path / "stream.log"
    stream_log.write_text("line1\n")

    scanner = _ChatIdScanner()
    backend = ClaudeBackend()

    # First scan: no chat_id
    result1 = scanner.scan("agent-1", stream_log, backend)
    assert result1 is None

    # Append new content with a chat_id
    with open(stream_log, "a") as f:
        f.write('{"sessionId": "sess-new"}\n')

    # Second scan: only reads new bytes, finds chat_id
    result2 = scanner.scan("agent-1", stream_log, backend)
    assert result2 == "sess-new"


# ---------------------------------------------------------------------------
# 6. chat_id persisted before agent death in monitor poll loop
# ---------------------------------------------------------------------------

def test_chat_id_persisted_before_agent_death_in_monitor(tmp_path):
    """Integration test: when stream.log contains a chat_id and the agent
    dies in the same poll cycle, db.update_agent must be called with
    chat_id before or during the cycle (chat_id is not lost).

    This verifies the _ChatIdScanner is invoked in the monitor loop
    BEFORE stall/heartbeat checks, per ADR Phase 4."""
    from phalanx.monitor.stall import AgentState, StallEvent

    agent = {
        "id": "worker-1",
        "team_id": "team-1",
        "status": "running",
        "artifact_status": None,
        "backend": "claude",
        "role": "worker",
        "model": None,
        "updated_at": 0,
    }
    db, pm, hm, sd = _make_deps([agent])
    db.get_agent.return_value = agent

    # Set up stream.log with a chat_id
    stream_log = tmp_path / "stream.log"
    stream_log.write_text('{"sessionId": "sess-abc"}\n')

    # Process is alive (so the monitor enters the active agent loop)
    mock_proc = MagicMock()
    mock_proc.stream_log = stream_log
    mock_proc.is_alive.return_value = True
    pm.get_process.return_value = mock_proc

    # Stall detector reports DEAD on this cycle
    dead_event = MagicMock()
    dead_event.state = AgentState.DEAD
    sd.check_agent.return_value = dead_event

    _run_one_tick(db, pm, hm, sd)

    # Assert chat_id was persisted
    chat_id_calls = [
        c for c in db.update_agent.call_args_list
        if "chat_id" in (c.kwargs or {}) and c.kwargs.get("chat_id") == "sess-abc"
        or (len(c.args) >= 1 and c.args[0] == "worker-1"
            and "chat_id" in (c.kwargs or {}))
    ]
    assert len(chat_id_calls) > 0, (
        "db.update_agent must be called with chat_id='sess-abc' "
        "during the poll cycle, even when the agent dies"
    )

    # Also verify the agent was marked dead (both things happen in same cycle)
    dead_calls = [
        c for c in db.update_agent.call_args_list
        if c == call("worker-1", status="dead")
    ]
    assert len(dead_calls) > 0, (
        "Agent should also be marked dead in the same cycle"
    )
