from __future__ import annotations

from phalanx.process.manager import ProcessManager


class _FakePane:
    def __init__(self, screens: list[list[str]]) -> None:
        self._screens = screens
        self._idx = 0
        self.sent: list[tuple[str, bool]] = []

    def capture_pane(self) -> list[str]:
        if self._idx < len(self._screens):
            out = self._screens[self._idx]
            self._idx += 1
            return out
        return self._screens[-1] if self._screens else []

    def send_keys(self, keys: str, enter: bool = True) -> None:
        self.sent.append((keys, enter))


class _Backend:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def deferred_prompt(self) -> bool:
        return False


def test_codex_startup_prompt_auto_accepts_workspace_trust(tmp_path):
    pm = ProcessManager(tmp_path)
    pane = _FakePane(
        [
            ["OpenAI Codex booting..."],
            [
                "Do you trust the contents of this directory?",
                "1. Yes, continue",
                "Press enter to continue",
            ],
        ]
    )

    pm._resolve_startup_prompts(pane, _Backend("codex"), "agent-1", timeout=0.1, poll_interval=0.0)

    assert pane.sent == [("1", True)]


def test_codex_startup_prompt_does_not_send_keys_without_trust_prompt(tmp_path):
    pm = ProcessManager(tmp_path)
    pane = _FakePane([["OpenAI Codex", "? for shortcuts"]])

    pm._resolve_startup_prompts(pane, _Backend("codex"), "agent-2", timeout=0.1, poll_interval=0.0)

    assert pane.sent == []


def test_non_codex_backend_skips_startup_prompt_resolution(tmp_path):
    pm = ProcessManager(tmp_path)
    pane = _FakePane(
        [["Do you trust the contents of this directory?", "1. Yes, continue", "Press enter"]]
    )

    pm._resolve_startup_prompts(
        pane, _Backend("cursor"), "agent-3", timeout=0.1, poll_interval=0.0
    )

    assert pane.sent == []


def test_startup_blocked_marker_written_for_login_selector(tmp_path):
    pm = ProcessManager(tmp_path)
    team_id = "team-x"
    agent_id = "agent-x"
    stream_log = pm._stream_log_path(team_id, agent_id)
    pane = _FakePane(
        [
            [
                "Claude Code can be used with your Claude subscription",
                "Select login method:",
                "1. Claude account with subscription",
                "2. Anthropic Console account",
            ]
        ]
    )

    pm._detect_startup_blocked(
        pane,
        _Backend("claude"),
        team_id,
        agent_id,
        stream_log,
        timeout=0.1,
        poll_interval=0.0,
    )

    marker = pm.consume_startup_blocked(team_id, agent_id)
    assert marker is not None
    assert marker["type"] == "startup_blocked"
    assert marker["backend"] == "claude"
    assert "select login method" in marker["prompt_excerpt"].lower()


def test_startup_blocked_not_written_when_progress_detected(tmp_path):
    pm = ProcessManager(tmp_path)
    team_id = "team-y"
    agent_id = "agent-y"
    stream_log = pm._stream_log_path(team_id, agent_id)
    pane = _FakePane([["Task completed", "Artifact written"]])

    pm._detect_startup_blocked(
        pane,
        _Backend("cursor"),
        team_id,
        agent_id,
        stream_log,
        timeout=0.1,
        poll_interval=0.0,
    )

    marker = pm.consume_startup_blocked(team_id, agent_id)
    assert marker is None


def test_startup_blocked_marker_written_for_idle_no_progress(tmp_path):
    pm = ProcessManager(tmp_path)
    team_id = "team-z"
    agent_id = "agent-z"
    stream_log = pm._stream_log_path(team_id, agent_id)
    pane = _FakePane(
        [
            ["OpenAI Codex", "? for shortcuts"],
            ["OpenAI Codex", "? for shortcuts"],
            ["OpenAI Codex", "? for shortcuts"],
        ]
    )

    pm._detect_startup_blocked(
        pane,
        _Backend("codex"),
        team_id,
        agent_id,
        stream_log,
        timeout=0.1,
        poll_interval=0.0,
    )

    marker = pm.consume_startup_blocked(team_id, agent_id)
    assert marker is not None
    assert marker["type"] == "startup_blocked"
