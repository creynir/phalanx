"""Stall detection and TUI screen scraper.

Phase 3 design:
- Continuously captures the tmux pane to detect if the screen is waiting
  for user input (permission prompt, workspace trust, etc.).
- When a prompt is detected, the agent transitions to 'blocked_on_prompt'.
- The exact screen text is preserved for the Main Agent to read and resolve.
- The idle timer is 30 minutes (1800s). If stream.log doesn't grow for
  30 minutes, the agent is killed to save compute.
- Uses exponential backoff for retries after stalls.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum

from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.process.manager import ProcessManager

# Avoid circular import — StateDB is only used for type hints here
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phalanx.db import StateDB

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes
SCREEN_CHECK_INTERVAL = 20  # seconds between screen scrapes
MAX_RETRY_BACKOFF = 300  # max 5 minutes between retries
IDLE_NUDGE_COOLDOWN = 60  # seconds between repeated agent_idle detections


class AgentState(str, Enum):
    RUNNING = "running"
    BLOCKED_ON_PROMPT = "blocked_on_prompt"
    IDLE_TIMEOUT = "idle_timeout"
    STALLED = "stalled"
    DEAD = "dead"


@dataclass
class PromptDetection:
    """Result of a screen scrape that detected a prompt."""

    agent_id: str
    prompt_type: str
    screen_text: str
    detected_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        return f"[{self.prompt_type}] {self.screen_text[:200]}"


@dataclass
class StallEvent:
    """Record of a stall or prompt detection."""

    agent_id: str
    state: AgentState
    screen_text: str = ""
    prompt_type: str = ""
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0


# -- Prompt patterns for TUI screen scraping --
# Each pattern has a name and a callable that checks screen lines.

_PROMPT_PATTERNS: list[tuple[str, callable]] = []


def _register_pattern(name: str):
    """Decorator to register a prompt detection pattern."""

    def decorator(fn):
        _PROMPT_PATTERNS.append((name, fn))
        return fn

    return decorator


@_register_pattern("workspace_trust")
def _check_workspace_trust(lines: list[str]) -> bool:
    text = "\n".join(lines)
    return "Workspace Trust" in text or (
        "Trust this workspace" in text and ("[a]" in text or "[y]" in text)
    )


@_register_pattern("permission_prompt")
def _check_permission_prompt(lines: list[str]) -> bool:
    text = "\n".join(lines[-10:])
    permission_keywords = [
        "Allow",
        "Deny",
        "approve",
        "reject",
        "Do you want to",
        "Permission required",
        "(y/n)",
        "[Y/n]",
        "[y/N]",
    ]
    return any(kw in text for kw in permission_keywords)


@_register_pattern("tool_approval")
def _check_tool_approval(lines: list[str]) -> bool:
    text = "\n".join(lines[-8:])
    return bool(
        re.search(
            r"(Run|Execute|Write|Delete|Create)\s+.*\?\s*(\[|$)",
            text,
        )
    )


@_register_pattern("error_prompt")
def _check_error_prompt(lines: list[str]) -> bool:
    text = "\n".join(lines[-5:])
    return bool(
        re.search(
            r"(retry|try again|abort|cancel)\s*[\[\(]",
            text,
            re.IGNORECASE,
        )
    )


@_register_pattern("agent_idle")
def _check_agent_idle(lines: list[str]) -> bool:
    """Detect if the agent has returned to its input prompt.

    Must NOT fire when the agent is actively generating or running a tool —
    the TUI chrome (follow-up bar, bottom bar) stays visible during work.
    """
    tail = "\n".join(lines[-8:]) if lines else ""

    active_indicators = [
        "Generating",
        "Running",
        "Thinking",
        "ctrl+c to stop",
        "Waiting for approval",
    ]
    if any(ind in tail for ind in active_indicators):
        return False

    return (
        "❯" in tail  # Claude Code prompt
        or "? for shortcuts" in tail  # Claude Code help hint
        or "→ Add a follow-up" in tail  # Cursor TUI idle prompt
        or "/ commands · @" in tail  # Cursor TUI bottom bar (idle state)
    )


class StallDetector:
    """Monitors agents for stalls, idle timeouts, and blocked prompts.

    Orchestrates HeartbeatMonitor (for log-based staleness) and
    ProcessManager (for screen capture). Called periodically from the
    monitor loop.
    """

    def __init__(
        self,
        process_manager: ProcessManager,
        heartbeat_monitor: HeartbeatMonitor,
        idle_timeout: int = IDLE_TIMEOUT_SECONDS,
        check_interval: int = SCREEN_CHECK_INTERVAL,
        db: "StateDB | None" = None,
    ) -> None:
        self._pm = process_manager
        self._hb = heartbeat_monitor
        self._idle_timeout = idle_timeout
        self._check_interval = check_interval
        self._db = db
        self._retry_counts: dict[str, int] = {}
        self._blocked_agents: dict[str, PromptDetection] = {}
        self._last_screen_check: dict[str, float] = {}
        self._last_idle_nudge: dict[str, float] = {}

    def check_agent(self, agent_id: str) -> StallEvent | None:
        """Check a single agent for stalls or prompts.

        Returns a StallEvent if something noteworthy happened, else None.
        """
        # 1. Check heartbeat (log-based staleness)
        hb_state = self._hb.check(agent_id)
        if hb_state is None:
            return None

        now = time.time()

        # 2. Check if agent is alive
        proc = self._pm.get_process(agent_id)
        if proc is None or not proc.is_alive():
            return StallEvent(
                agent_id=agent_id,
                state=AgentState.DEAD,
                timestamp=now,
            )

        # 3. 30-minute idle timeout
        if hb_state.is_stale(now):
            logger.warning(
                "Agent %s has been idle for >%ds — idle timeout",
                agent_id,
                self._idle_timeout,
            )
            return StallEvent(
                agent_id=agent_id,
                state=AgentState.IDLE_TIMEOUT,
                timestamp=now,
            )

        # 4. TUI screen scrape (rate limited)
        last_check = self._last_screen_check.get(agent_id, 0)
        if (now - last_check) < self._check_interval:
            return None  # not time yet

        self._last_screen_check[agent_id] = now
        screen = self._pm.capture_screen(agent_id)
        if screen is None:
            logger.warning(
                "capture_screen returned None for agent %s — tmux session may be gone", agent_id
            )
            return None

        # 5. Check for blocked_on_prompt
        prompt_detection = self._detect_prompt(agent_id, screen)
        if prompt_detection:
            self._blocked_agents[agent_id] = prompt_detection
            logger.info(
                "Agent %s blocked on prompt: %s",
                agent_id,
                prompt_detection.prompt_type,
            )
            return StallEvent(
                agent_id=agent_id,
                state=AgentState.BLOCKED_ON_PROMPT,
                screen_text=prompt_detection.screen_text,
                prompt_type=prompt_detection.prompt_type,
                timestamp=now,
            )

        # Agent is running normally
        return None

    def check_all(self) -> list[StallEvent]:
        """Check all registered agents. Returns list of events."""
        events = []
        for agent_id in list(self._hb._states.keys()):
            event = self.check_agent(agent_id)
            if event:
                events.append(event)
        return events

    def get_blocked_prompt(self, agent_id: str) -> PromptDetection | None:
        """Get the prompt detection for a blocked agent."""
        return self._blocked_agents.get(agent_id)

    def clear_blocked(self, agent_id: str) -> None:
        """Clear the blocked state after the prompt has been resolved."""
        self._blocked_agents.pop(agent_id, None)

    def get_retry_delay(self, agent_id: str) -> float:
        """Compute exponential backoff delay for retries."""
        count = self._retry_counts.get(agent_id, 0)
        delay = min(2**count * 5, MAX_RETRY_BACKOFF)
        return delay

    def record_retry(self, agent_id: str) -> int:
        """Record a retry attempt. Returns the new count."""
        count = self._retry_counts.get(agent_id, 0) + 1
        self._retry_counts[agent_id] = count
        return count

    def reset_retries(self, agent_id: str) -> None:
        self._retry_counts.pop(agent_id, None)

    def _agent_has_artifact(self, agent_id: str) -> bool:
        """Return True if the agent has already written an artifact."""
        if self._db is None:
            return False
        try:
            agent = self._db.get_agent(agent_id)
            return agent is not None and agent.get("artifact_status") is not None
        except Exception as e:
            logger.warning("Failed to check artifact status for %s: %s", agent_id, e)
            return False

    def _detect_prompt(self, agent_id: str, screen: list[str]) -> PromptDetection | None:
        """Run all registered prompt patterns against the screen."""
        for pattern_name, checker in _PROMPT_PATTERNS:
            if pattern_name == "agent_idle":
                # Agent sitting at prompt is only a problem if it hasn't written
                # its artifact yet — otherwise it finished normally.
                if not self._agent_has_artifact(agent_id):
                    now = time.time()
                    last_nudge = self._last_idle_nudge.get(agent_id, 0)
                    if (now - last_nudge) >= IDLE_NUDGE_COOLDOWN:
                        try:
                            if checker(screen):
                                self._last_idle_nudge[agent_id] = now
                                screen_text = "\n".join(screen)
                                logger.info(
                                    "Agent %s is idle at prompt without artifact — nudge needed",
                                    agent_id,
                                )
                                return PromptDetection(
                                    agent_id=agent_id,
                                    prompt_type="agent_idle",
                                    screen_text=screen_text,
                                )
                        except Exception as e:
                            logger.debug("agent_idle check failed for %s: %s", agent_id, e)
                continue

            try:
                if checker(screen):
                    screen_text = "\n".join(screen)
                    return PromptDetection(
                        agent_id=agent_id,
                        prompt_type=pattern_name,
                        screen_text=screen_text,
                    )
            except Exception as e:
                logger.debug(
                    "Prompt pattern %s failed for %s: %s",
                    pattern_name,
                    agent_id,
                    e,
                )
        return None
