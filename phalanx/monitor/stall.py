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
STARTUP_GRACE_SECONDS = 120  # ignore DEAD during TUI cold-start
STARTUP_DEAD_THRESHOLD = 3  # consecutive DEAD checks before confirming


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


@_register_pattern("connection_lost")
def _check_connection_lost(lines: list[str]) -> bool:
    text = "\n".join(lines[-8:])
    return bool(
        re.search(
            r"(Connection lost|connection error|disconnected|Session expired)",
            text,
            re.IGNORECASE,
        )
    )


@_register_pattern("process_exited")
def _check_process_exited(lines: list[str]) -> bool:
    """Detect when the agent binary has crashed and the tmux session fell
    back to a bare shell prompt.  Garbled output like ``zsh: command not found``
    is a strong signal that buffered agent output was dumped into the shell.

    Also catches silent exits where only a bare prompt remains.
    """
    if not lines:
        return False

    filtered = _filter_code_blocks(lines[-12:])

    error_pattern = re.compile(
        r"zsh:|bash:|sh:|command not found|parse error|no such file",
        re.IGNORECASE,
    )
    error_lines = sum(1 for ln in filtered if error_pattern.search(ln))

    if error_lines >= 2:
        return True

    if error_lines >= 1:
        return False

    last_lines = [ln.strip() for ln in lines[-4:] if ln.strip()]
    if last_lines:
        last = last_lines[-1]
        if re.match(r"^[\w@.~/:, ()-]*[$%#>]\s*$", last):
            return True

    return False


def _filter_code_blocks(lines: list[str]) -> list[str]:
    """Remove lines that appear inside markdown code fences."""
    result = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            result.append(line)
    return result


@_register_pattern("buffer_corrupted")
def _check_buffer_corrupted(lines: list[str]) -> bool:
    """Detect when send_keys injection has corrupted the terminal buffer,
    leaving the shell in quote-continuation mode.
    """
    if not lines:
        return False
    tail = "\n".join(lines[-8:])
    return bool(
        re.search(
            r"^(quote|dquote|bquote|heredoc)>",
            tail,
            re.MULTILINE,
        )
    )


@_register_pattern("rate_limited")
def _check_rate_limited(lines: list[str]) -> bool:
    """Detect API rate limit errors in stream output."""
    if not lines:
        return False
    tail = "\n".join(lines[-12:])
    return bool(
        re.search(
            r"(rate.?limit|429 Too Many Requests|quota exceeded|"
            r"too many requests|throttled|RateLimitError)",
            tail,
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
        self._first_seen: dict[str, float] = {}
        self._consecutive_dead: dict[str, int] = {}

    def check_agent(self, agent_id: str) -> StallEvent | None:
        """Check a single agent for stalls or prompts.

        Returns a StallEvent if something noteworthy happened, else None.
        """
        # 1. Check heartbeat (log-based staleness)
        hb_state = self._hb.check(agent_id)
        if hb_state is None:
            return None

        now = time.time()

        if agent_id not in self._first_seen:
            self._first_seen[agent_id] = now

        # 2. Check if agent is alive
        proc = self._pm.get_process(agent_id)
        if proc is None or not proc.is_alive():
            age = now - self._first_seen[agent_id]
            consecutive = self._consecutive_dead.get(agent_id, 0) + 1
            self._consecutive_dead[agent_id] = consecutive

            if age < STARTUP_GRACE_SECONDS or consecutive < STARTUP_DEAD_THRESHOLD:
                logger.debug(
                    "Agent %s looks dead but within startup grace (%ds, check %d/%d) — skipping",
                    agent_id,
                    int(age),
                    consecutive,
                    STARTUP_DEAD_THRESHOLD,
                )
                return None

            return StallEvent(
                agent_id=agent_id,
                state=AgentState.DEAD,
                timestamp=now,
            )
        else:
            self._consecutive_dead.pop(agent_id, None)

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
            age = now - self._first_seen.get(agent_id, now)
            if age < STARTUP_GRACE_SECONDS:
                logger.debug(
                    "capture_screen returned None for agent %s but within startup grace (%ds) — skipping",
                    agent_id,
                    int(age),
                )
                return None
            logger.warning("capture_screen returned None for agent %s — treating as dead", agent_id)
            return StallEvent(
                agent_id=agent_id,
                state=AgentState.DEAD,
                timestamp=now,
            )

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

    def _agent_has_escalation(self, agent_id: str) -> bool:
        """Return True if the agent wrote an escalation artifact (not idle)."""
        if self._db is None:
            return False
        try:
            agent = self._db.get_agent(agent_id)
            return agent is not None and agent.get("artifact_status") == "escalation"
        except Exception as e:
            logger.warning("Failed to check escalation status for %s: %s", agent_id, e)
            return False

    def _detect_prompt(self, agent_id: str, screen: list[str]) -> PromptDetection | None:
        """Run all registered prompt patterns against the screen."""
        for pattern_name, checker in _PROMPT_PATTERNS:
            if pattern_name == "agent_idle":
                # Agent sitting at prompt after writing an escalation artifact
                # is NOT idle — it's waiting for Outer Loop intervention.
                if self._agent_has_escalation(agent_id):
                    continue
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
