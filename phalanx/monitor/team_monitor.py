"""Per-team monitor daemon.

Spawned in its own tmux session by create-team. Watches all agents in the
team via heartbeat + stall detection. Persists state to DB.

Responsibilities:
- Check heartbeats every poll_interval seconds
- Persist last_heartbeat to DB for each agent
- Enforce 30-min idle timeout: kill idle agents, update DB
- Detect dead agents (tmux session gone)
- Mark team dead when all agents are dead/suspended
- Exit when team is fully dead
- Parse token usage from stream logs and record to CostAggregator
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from phalanx.comms.messaging import deliver_message
from phalanx.costs.aggregator import CostAggregator
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.monitor.stall import AgentState, StallDetector
from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)


class _StreamLogCostScanner:
    """Incrementally scans stream.log files for token usage lines.

    Tracks a read offset per agent so each chunk of new output is parsed
    exactly once — no double-counting across monitor poll cycles.
    """

    def __init__(self) -> None:
        self._offsets: dict[str, int] = {}

    def scan(
        self,
        agent_id: str,
        stream_log: Path,
        backend_name: str,
        aggregator: CostAggregator,
        team_id: str,
        role: str,
        model: str | None,
    ) -> None:
        """Read new bytes from stream_log and record any token usage found."""
        from phalanx.backends import get_backend

        if not stream_log.exists():
            return

        try:
            file_size = stream_log.stat().st_size
        except OSError:
            return

        offset = self._offsets.get(agent_id, 0)
        if file_size <= offset:
            return

        try:
            with open(stream_log, "rb") as fh:
                fh.seek(offset)
                new_bytes = fh.read(file_size - offset)
            self._offsets[agent_id] = file_size
        except OSError:
            return

        try:
            new_text = new_bytes.decode("utf-8", errors="replace")
        except Exception:
            return

        try:
            backend = get_backend(backend_name)
        except Exception:
            return

        for line in new_text.splitlines():
            try:
                usage = backend.parse_token_usage(line)
            except Exception:
                continue
            if usage is None:
                continue

            input_tokens = int(usage.get("input_tokens") or usage.get("tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)

            if input_tokens > 0 or output_tokens > 0:
                aggregator.record_usage(
                    team_id=team_id,
                    agent_id=agent_id,
                    role=role,
                    backend=backend_name,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

    def reset(self, agent_id: str) -> None:
        """Reset offset for an agent (e.g., after restart)."""
        self._offsets.pop(agent_id, None)


def run_team_monitor(
    team_id: str,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    stall_detector: StallDetector,
    poll_interval: int = 20,
    idle_timeout: int = 1800,
    lead_agent_id: str | None = None,
    message_dir: Path | None = None,
    phalanx_root: Path | None = None,
    cost_aggregator: CostAggregator | None = None,
) -> None:
    """Blocking loop that monitors all agents in a team.

    Runs until all agents are in a terminal state (dead/suspended/failed).
    """
    logger.info("Team monitor started for %s (poll=%ds)", team_id, poll_interval)

    _cost_scanner = _StreamLogCostScanner()

    while True:
        try:
            agents = db.list_agents(team_id)
        except Exception as e:
            logger.error(
                "Monitor DB error listing agents for team %s: %s", team_id, e, exc_info=True
            )
            time.sleep(poll_interval)
            continue

        if not agents:
            logger.info("No agents found for team %s, exiting monitor", team_id)
            break

        active_count = 0
        for agent in agents:
            if agent["status"] in ("dead", "failed"):
                continue

            if agent["status"] == "suspended":
                if _should_wake_suspended(db, agent):
                    logger.info(
                        "Waking suspended agent %s — post-artifact directives detected",
                        agent["id"],
                    )
                    active_count += 1
                    _wake_suspended_agent(
                        phalanx_root=process_manager._root,
                        db=db,
                        process_manager=process_manager,
                        heartbeat_monitor=heartbeat_monitor,
                        agent=agent,
                        lead_agent_id=lead_agent_id,
                        message_dir=message_dir,
                    )
                continue

            agent_id = agent["id"]
            active_count += 1

            # Re-discover agents that were resumed externally (e.g., by
            # the team lead calling `phalanx resume-agent`).  After
            # kill_agent the ProcessManager forgets the agent; we need
            # to pick up the new tmux session so stall_detector doesn't
            # immediately report DEAD.
            if process_manager.get_process(agent_id) is None:
                proc = process_manager.discover_agent(team_id, agent_id)
                if proc is not None:
                    stream_log = proc.stream_log
                    if heartbeat_monitor.get_state(agent_id) is None:
                        heartbeat_monitor.register(agent_id, stream_log)
                    # Reset cost scanner offset so resumed agents are re-scanned
                    _cost_scanner.reset(agent_id)
                    logger.info("Re-discovered resumed agent %s", agent_id)

            # Scan stream.log for new token usage lines (cost tracking).
            # Uses the ProcessManager's tracked stream_log path so we always
            # read the same file the heartbeat monitor watches.
            if cost_aggregator is not None:
                proc = process_manager.get_process(agent_id)
                if proc is not None:
                    _cost_scanner.scan(
                        agent_id=agent_id,
                        stream_log=proc.stream_log,
                        backend_name=agent.get("backend") or "cursor",
                        aggregator=cost_aggregator,
                        team_id=team_id,
                        role=agent.get("role") or "worker",
                        model=agent.get("model"),
                    )

            try:
                event = stall_detector.check_agent(agent_id)

                # Only update heartbeat in DB when stream.log shows new activity
                prev_hb = heartbeat_monitor.get_state(agent_id)
                prev_ts = prev_hb.last_heartbeat if prev_hb else 0.0
                updated = heartbeat_monitor.check(agent_id)
                if updated is not None and updated.last_heartbeat > prev_ts:
                    db.update_heartbeat(agent_id)

                # Check for newly written artifacts regardless of stall events.
                refreshed = db.get_agent(agent_id)
                if refreshed and refreshed.get("artifact_status"):
                    prev_status = agent.get("artifact_status")
                    new_status = refreshed["artifact_status"]
                    if new_status == "success" and prev_status != "success":
                        _notify_lead(
                            process_manager,
                            lead_agent_id,
                            message_dir,
                            "worker_done",
                            agent_id,
                        )
                    elif new_status == "escalation" and prev_status != "escalation":
                        _notify_lead(
                            process_manager,
                            lead_agent_id,
                            message_dir,
                            "worker_escalation",
                            agent_id,
                            detail=(
                                "agent wrote escalation artifact — outer loop intervention needed"
                            ),
                        )

                if event is None:
                    continue

                if event.state == AgentState.DEAD:
                    logger.warning("Agent %s is dead (tmux gone)", agent_id)
                    db.update_agent(agent_id, status="dead")
                    db.log_event(team_id, "agent_dead", agent_id=agent_id)
                    _notify_lead(
                        process_manager, lead_agent_id, message_dir, "worker_dead", agent_id
                    )

                elif event.state == AgentState.IDLE_TIMEOUT:
                    logger.warning("Agent %s idle timeout (%ds)", agent_id, idle_timeout)
                    process_manager.kill_agent(agent_id)
                    db.update_agent(agent_id, status="suspended")
                    db.log_event(
                        team_id,
                        "idle_timeout",
                        agent_id=agent_id,
                        payload={"timeout_seconds": idle_timeout},
                    )
                    _notify_lead(
                        process_manager, lead_agent_id, message_dir, "worker_timeout", agent_id
                    )

                elif event.state == AgentState.BLOCKED_ON_PROMPT:
                    logger.info(
                        "Agent %s blocked on prompt: %s",
                        agent_id,
                        event.prompt_type,
                    )
                    db.update_agent(
                        agent_id,
                        status="blocked_on_prompt",
                        prompt_state=event.prompt_type,
                        prompt_screen=event.screen_text[:500],
                    )
                    db.log_event(
                        team_id,
                        "blocked_on_prompt",
                        agent_id=agent_id,
                        payload={"prompt_type": event.prompt_type},
                    )

                    if event.prompt_type == "agent_idle" and agent_id != lead_agent_id:
                        _nudge_idle_agent(process_manager, agent_id, message_dir)
                    elif event.prompt_type in ("connection_lost", "process_exited"):
                        _handle_ghost_or_crash(
                            process_manager,
                            db,
                            heartbeat_monitor,
                            team_id,
                            agent_id,
                            lead_agent_id,
                            message_dir,
                        )
                    elif event.prompt_type == "buffer_corrupted":
                        _handle_buffer_corruption(
                            process_manager,
                            db,
                            heartbeat_monitor,
                            team_id,
                            agent_id,
                            lead_agent_id,
                            message_dir,
                        )
                    elif event.prompt_type == "rate_limited":
                        _handle_rate_limit(
                            process_manager,
                            db,
                            team_id,
                            agent_id,
                            lead_agent_id,
                            message_dir,
                        )
                    else:
                        _notify_lead(
                            process_manager,
                            lead_agent_id,
                            message_dir,
                            "worker_blocked",
                            agent_id,
                            detail=event.prompt_type or "",
                        )

            except Exception as e:
                logger.error(
                    "Monitor error on agent %s: %s", agent.get("id", "?"), e, exc_info=True
                )
                continue

        if active_count == 0:
            logger.info("All agents in team %s are in terminal state", team_id)
            db.update_team_status(team_id, "dead")
            db.log_event(team_id, "team_dead")
            break

        time.sleep(poll_interval)

    logger.info("Team monitor for %s exiting", team_id)


def _notify_lead(
    process_manager: ProcessManager,
    lead_agent_id: str | None,
    message_dir: Path | None,
    event_type: str,
    agent_id: str,
    detail: str = "",
) -> None:
    if lead_agent_id is None:
        return
    msg = f"[PHALANX EVENT] {event_type}: worker {agent_id}"
    if detail:
        msg += f" — {detail}"
    msg += ". Check status and decide next action."
    try:
        deliver_message(process_manager, lead_agent_id, msg, message_dir)
    except Exception as e:
        logger.warning("Failed to notify lead %s: %s", lead_agent_id, e)


def _handle_ghost_or_crash(
    process_manager: ProcessManager,
    db: StateDB,
    heartbeat_monitor: HeartbeatMonitor,
    team_id: str,
    agent_id: str,
    lead_agent_id: str | None,
    message_dir: Path | None,
) -> None:
    """Handle ghost session or crash with restart loop protection.

    Tracks ghost_restart_count in DB. When the count exceeds
    max_ghost_restarts, escalates to the Outer Loop (Engineering Manager)
    instead of restarting again — breaking the restart loop.
    """
    restart_count = db.increment_ghost_restart(agent_id)
    restart_limit = db.get_ghost_restart_limit(agent_id)

    if restart_count > restart_limit:
        logger.error(
            "Agent %s hit ghost restart limit (%d/%d) — escalating to Outer Loop",
            agent_id,
            restart_count,
            restart_limit,
        )
        process_manager.kill_agent(agent_id)
        db.update_agent(agent_id, status="failed")
        db.log_event(
            team_id,
            "ghost_loop_escalation",
            agent_id=agent_id,
            payload={"restart_count": restart_count, "limit": restart_limit},
        )

        db.create_engineering_manager_entry(
            team_id=team_id,
            trigger_source="ghost_loop",
            decision_json=None,
        )

        _notify_lead(
            process_manager,
            lead_agent_id,
            message_dir,
            "ghost_loop_escalation",
            agent_id,
            detail=(
                f"agent hit ghost restart limit ({restart_count}/{restart_limit}) "
                "— outer loop intervention needed"
            ),
        )
        return

    _auto_restart_agent(
        process_manager,
        db,
        heartbeat_monitor,
        team_id,
        agent_id,
        lead_agent_id,
        message_dir,
    )


def _auto_restart_agent(
    process_manager: ProcessManager,
    db: StateDB,
    heartbeat_monitor: HeartbeatMonitor,
    team_id: str,
    agent_id: str,
    lead_agent_id: str | None,
    message_dir: Path | None,
) -> None:
    """Auto-restart an agent that hit a recoverable infrastructure error.

    Kills the stuck session, marks it dead, then attempts resume.
    Notifies the lead of the restart.
    """
    from phalanx.team.orchestrator import resume_single_agent

    logger.warning("Auto-restarting agent %s (infrastructure failure)", agent_id)
    process_manager.kill_agent(agent_id)
    db.update_agent(agent_id, status="dead")

    try:
        resume_single_agent(
            phalanx_root=process_manager._root,
            db=db,
            process_manager=process_manager,
            heartbeat_monitor=heartbeat_monitor,
            agent_id=agent_id,
            auto_approve=True,
        )
        db.reset_ghost_restart_count(agent_id)
        logger.info("Auto-restarted agent %s successfully", agent_id)
        _notify_lead(
            process_manager,
            lead_agent_id,
            message_dir,
            "worker_restarted",
            agent_id,
            detail="infrastructure failure — auto-recovered by daemon",
        )
    except Exception as e:
        logger.error("Failed to auto-restart agent %s: %s", agent_id, e)
        _notify_lead(
            process_manager,
            lead_agent_id,
            message_dir,
            "worker_restart_failed",
            agent_id,
            detail=str(e),
        )


def _nudge_idle_agent(
    process_manager: ProcessManager,
    agent_id: str,
    message_dir: Path | None = None,
) -> None:
    """Send a nudge to an agent that is idle at the prompt without an artifact.

    Uses file-based delivery to avoid prompt injection vulnerabilities.
    """
    nudge = (
        "You have not completed your task yet. "
        "Stop summarising and start executing. "
        "Complete the task described above, then call "
        "`phalanx write-artifact` with your results. Do not ask questions."
    )
    try:
        deliver_message(process_manager, agent_id, nudge, message_dir)
        logger.info("Nudged idle agent %s", agent_id)
    except Exception as e:
        logger.warning("Failed to nudge agent %s: %s", agent_id, e)


def _handle_buffer_corruption(
    process_manager: ProcessManager,
    db: StateDB,
    heartbeat_monitor: HeartbeatMonitor,
    team_id: str,
    agent_id: str,
    lead_agent_id: str | None,
    message_dir: Path | None,
) -> None:
    """Handle buffer corruption from prompt injection.

    Sends Ctrl-C to escape quote mode, then falls back to file-based delivery.
    After 3 failures, escalates to Engineering Manager.
    """
    logger.warning("Buffer corruption detected for agent %s", agent_id)

    try:
        process_manager.send_keys(agent_id, "C-c", enter=False)
    except Exception:
        pass

    agent = db.get_agent(agent_id)
    attempts = (agent.get("attempts") or 0) + 1 if agent else 1
    db.update_agent(agent_id, attempts=attempts)
    db.log_event(
        team_id,
        "buffer_corrupted",
        agent_id=agent_id,
        payload={"attempts": attempts},
    )

    if attempts >= 3:
        logger.error(
            "Agent %s buffer corruption repeated %d times — escalating", agent_id, attempts
        )
        _notify_lead(
            process_manager,
            lead_agent_id,
            message_dir,
            "prompt_delivery_failure",
            agent_id,
            detail=f"buffer corruption x{attempts} — needs outer loop intervention",
        )
    else:
        _notify_lead(
            process_manager,
            lead_agent_id,
            message_dir,
            "worker_blocked",
            agent_id,
            detail="buffer_corrupted — escaped quote mode, retry via file delivery",
        )


def _should_wake_suspended(db: StateDB, agent: dict) -> bool:
    """Check if a suspended agent with a success artifact should be woken.

    Returns True if there are feed messages posted after the agent's artifact,
    indicating the Engineering Manager or team lead wants it to do new work.
    """
    artifact_status = agent.get("artifact_status")
    if artifact_status not in ("success", "escalation"):
        return False

    team_id = agent["team_id"]
    agent_updated = agent.get("updated_at", 0)

    try:
        recent_feed = db.get_feed(team_id, limit=10, since=agent_updated)
        return len(recent_feed) > 0
    except Exception:
        return False


def _wake_suspended_agent(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    agent: dict,
    lead_agent_id: str | None,
    message_dir: Path | None,
) -> None:
    """Resume a suspended agent that has new directives.

    v1.0.0: Resets artifact_status to None before resuming so the agent
    processes new directives instead of treating its prior success as terminal.
    """
    from phalanx.team.orchestrator import resume_single_agent

    agent_id = agent["id"]
    try:
        db.update_agent(agent_id, artifact_status=None)
        resume_single_agent(
            phalanx_root=phalanx_root,
            db=db,
            process_manager=process_manager,
            heartbeat_monitor=heartbeat_monitor,
            agent_id=agent_id,
            auto_approve=True,
        )
        _notify_lead(
            process_manager,
            lead_agent_id,
            message_dir,
            "worker_woken",
            agent_id,
            detail="suspended agent woken — post-artifact directives detected",
        )
    except Exception as e:
        logger.error("Failed to wake suspended agent %s: %s", agent_id, e)


RATE_LIMIT_BACKOFF_SECONDS = 60


def _handle_rate_limit(
    process_manager: ProcessManager,
    db: StateDB,
    team_id: str,
    agent_id: str,
    lead_agent_id: str | None,
    message_dir: Path | None,
) -> None:
    """Handle API rate limiting.

    Does NOT immediately restart — logs the event and notifies lead.
    The Engineering Manager can swap models if the limit persists.
    """
    logger.warning("Agent %s hit API rate limit", agent_id)
    db.log_event(
        team_id,
        "rate_limited",
        agent_id=agent_id,
    )
    _notify_lead(
        process_manager,
        lead_agent_id,
        message_dir,
        "worker_blocked",
        agent_id,
        detail=f"rate_limited — backoff {RATE_LIMIT_BACKOFF_SECONDS}s before retry",
    )
