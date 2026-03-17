"""Pytest fixtures for phalanx E2E tests."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from helpers import PHALANX_SOURCE, TEST_IDLE_TIMEOUT_DEFAULT, TEST_POLL_INTERVAL

# Make phalanx importable
sys.path.insert(0, str(PHALANX_SOURCE))


@pytest.fixture
def phalanx_root(tmp_path):
    root = tmp_path / ".phalanx"
    root.mkdir()
    (root / "teams").mkdir()
    return root


@pytest.fixture
def state_db(phalanx_root):
    from phalanx.db import StateDB
    return StateDB(phalanx_root / "state.db")


@pytest.fixture
def process_manager(phalanx_root):
    from phalanx.process.manager import ProcessManager
    return ProcessManager(phalanx_root)


@pytest.fixture
def heartbeat_monitor():
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    return HeartbeatMonitor(idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT)


@pytest.fixture
def stall_detector(process_manager, heartbeat_monitor, state_db):
    from phalanx.monitor.stall import StallDetector
    return StallDetector(
        process_manager=process_manager,
        heartbeat_monitor=heartbeat_monitor,
        idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
        db=state_db,
    )


@pytest.fixture(autouse=True)
def cleanup_tmux_sessions():
    """Kill all phalanx-* tmux sessions after each test."""
    yield
    try:
        import libtmux
        server = libtmux.Server()
        for s in list(server.sessions):
            if s.name and s.name.startswith("phalanx-"):
                try:
                    s.kill()
                except Exception:
                    pass
    except Exception:
        pass


@pytest.fixture
def fake_registry(monkeypatch):
    """Register FakeBackend variants by name into _BACKENDS."""
    from phalanx.backends import registry as _reg

    # Add the tests/e2e directory to path so fake_backend can be imported
    e2e_dir = str(Path(__file__).parent)
    if e2e_dir not in sys.path:
        sys.path.insert(0, e2e_dir)

    from fake_backend import FakeBackend

    registered = {}

    def register(name, **kwargs):
        instance = FakeBackend(backend_name=name, **kwargs)
        registered[name] = instance
        # registry.get_backend(name) calls _BACKENDS[name]()
        # We need to return the same instance each time
        monkeypatch.setitem(_reg._BACKENDS, name, lambda _inst=instance: _inst)
        return instance

    return register


def run_monitor_background(
    team_id,
    db,
    pm,
    hb,
    sd,
    poll_interval=TEST_POLL_INTERVAL,
    idle_timeout=TEST_IDLE_TIMEOUT_DEFAULT,
    lead_agent_id=None,
    phalanx_root=None,
):
    """Start run_team_monitor in a daemon thread. Returns the thread."""
    from phalanx.monitor.team_monitor import run_team_monitor

    t = threading.Thread(
        target=run_team_monitor,
        kwargs=dict(
            team_id=team_id,
            db=db,
            process_manager=pm,
            heartbeat_monitor=hb,
            stall_detector=sd,
            poll_interval=poll_interval,
            idle_timeout=idle_timeout,
            lead_agent_id=lead_agent_id,
            message_dir=phalanx_root / "teams" / team_id / "messages" if phalanx_root else None,
            phalanx_root=phalanx_root,
            cost_aggregator=None,
        ),
        daemon=True,
    )
    t.start()
    return t
