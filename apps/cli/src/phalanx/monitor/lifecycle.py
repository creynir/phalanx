"""Agent lifecycle state machine and monitor loop.

Runs as a blocking command (`phalanx monitor <agent-id>`) that watches
an agent through its entire lifecycle, handling stalls, prompts,
retries, and completion.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.monitor.stall import AgentState, StallDetector
from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)

MONITOR_POLL_INTERVAL = 20  # seconds


@dataclass
class MonitorResult:
    """Result of monitoring an agent to completion."""

    agent_id: str
    final_state: str
    artifact_status: str | None = None
    screen_text: str = ""
    prompt_type: str = ""
    retry_count: int = 0
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "status": self.final_state,
            "artifact_status": self.artifact_status,
            "retry_count": self.retry_count,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
        }


def run_monitor_loop(
    agent_id: str,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    stall_detector: StallDetector,
    max_retries: int = 3,
    max_runtime: int = 1800,
    poll_interval: int = MONITOR_POLL_INTERVAL,
    on_blocked: "Callable | None" = None,
    on_stall: "Callable | None" = None,
) -> MonitorResult:
    """Blocking DEM-style monitoring loop for a single agent.

    Periodically checks heartbeat and screen state. Handles:
    - Stall detection → kill + retry with backoff
    - Blocked on prompt → callback to escalate
    - Idle timeout (30m) → kill + mark suspended
    - Agent death → mark dead
    - Max runtime exceeded → kill + mark failed

    Args:
        on_blocked: Called with (agent_id, StallEvent) when blocked on prompt.
                    If it returns True, monitoring continues. False stops.
        on_stall: Called with (agent_id, StallEvent) when stalled.
                  Return True to retry, False to give up.
    """
    start_time = time.time()
    retry_count = 0

    while True:
        elapsed = time.time() - start_time

        if elapsed > max_runtime:
            logger.warning(
                "Agent %s exceeded max runtime of %ds",
                agent_id,
                max_runtime,
            )
            process_manager.kill_agent(agent_id)
            return MonitorResult(
                agent_id=agent_id,
                final_state="failed",
                retry_count=retry_count,
                elapsed_seconds=elapsed,
            )

        event = stall_detector.check_agent(agent_id)

        if event is None:
            time.sleep(poll_interval)
            continue

        if event.state == AgentState.DEAD:
            logger.info("Agent %s is dead", agent_id)
            return MonitorResult(
                agent_id=agent_id,
                final_state="dead",
                retry_count=retry_count,
                elapsed_seconds=time.time() - start_time,
            )

        if event.state == AgentState.BLOCKED_ON_PROMPT:
            logger.info(
                "Agent %s blocked on prompt: %s",
                agent_id,
                event.prompt_type,
            )
            if on_blocked:
                should_continue = on_blocked(agent_id, event)
                if not should_continue:
                    return MonitorResult(
                        agent_id=agent_id,
                        final_state="blocked_on_prompt",
                        screen_text=event.screen_text,
                        prompt_type=event.prompt_type,
                        retry_count=retry_count,
                        elapsed_seconds=time.time() - start_time,
                    )
            else:
                return MonitorResult(
                    agent_id=agent_id,
                    final_state="blocked_on_prompt",
                    screen_text=event.screen_text,
                    prompt_type=event.prompt_type,
                    retry_count=retry_count,
                    elapsed_seconds=time.time() - start_time,
                )

        if event.state == AgentState.IDLE_TIMEOUT:
            logger.warning("Agent %s hit idle timeout", agent_id)
            process_manager.kill_agent(agent_id)
            return MonitorResult(
                agent_id=agent_id,
                final_state="suspended",
                retry_count=retry_count,
                elapsed_seconds=time.time() - start_time,
            )

        if event.state == AgentState.STALLED:
            retry_count += 1
            if retry_count > max_retries:
                logger.error(
                    "Agent %s stalled %d times, giving up",
                    agent_id,
                    retry_count,
                )
                process_manager.kill_agent(agent_id)
                return MonitorResult(
                    agent_id=agent_id,
                    final_state="failed",
                    retry_count=retry_count,
                    elapsed_seconds=time.time() - start_time,
                )

            logger.warning(
                "Agent %s stalled (attempt %d/%d), retrying...",
                agent_id,
                retry_count,
                max_retries,
            )
            if on_stall:
                should_retry = on_stall(agent_id, event)
                if not should_retry:
                    return MonitorResult(
                        agent_id=agent_id,
                        final_state="failed",
                        retry_count=retry_count,
                        elapsed_seconds=time.time() - start_time,
                    )

            delay = stall_detector.get_retry_delay(agent_id)
            stall_detector.record_retry(agent_id)
            logger.info("Waiting %.1fs before retry...", delay)
            time.sleep(delay)

        time.sleep(poll_interval)
