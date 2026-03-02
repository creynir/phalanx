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
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from phalanx.comms.messaging import deliver_message
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.monitor.stall import AgentState, StallDetector
from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)


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
) -> None:
    """Blocking loop that monitors all agents in a team.

    Runs until all agents are in a terminal state (dead/suspended/failed).
    """
    logger.info("Team monitor started for %s (poll=%ds)", team_id, poll_interval)

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
            if agent["status"] in ("dead", "failed", "suspended"):
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
                    logger.info("Re-discovered resumed agent %s", agent_id)

            try:
                event = stall_detector.check_agent(agent_id)

                # Only update heartbeat in DB when stream.log shows new activity
                prev_hb = heartbeat_monitor.get_state(agent_id)
                prev_ts = prev_hb.last_heartbeat if prev_hb else 0.0
                updated = heartbeat_monitor.check(agent_id)
                if updated is not None and updated.last_heartbeat > prev_ts:
                    db.update_heartbeat(agent_id)

                # Check for newly written artifacts regardless of stall events.
                # This must run before the `continue` so the lead is notified
                # as soon as a worker's artifact_status flips to success.
                refreshed = db.get_agent(agent_id)
                if refreshed and refreshed.get("artifact_status") == "success":
                    if agent.get("artifact_status") != "success":
                        _notify_lead(
                            process_manager,
                            lead_agent_id,
                            message_dir,
                            "worker_done",
                            agent_id,
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
                        _nudge_idle_agent(process_manager, agent_id)
                    elif event.prompt_type in ("connection_lost", "process_exited"):
                        _auto_restart_agent(
                            process_manager,
                            db,
                            heartbeat_monitor,
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


def _nudge_idle_agent(process_manager: ProcessManager, agent_id: str) -> None:
    """Send a nudge to an agent that is idle at the prompt without an artifact.

    The agent has read its task and responded conversationally. We inject
    an imperative follow-up so it actually executes.
    """
    nudge = (
        "You have not completed your task yet. "
        "Stop summarising and start executing. "
        "Complete the task described above, then call "
        "`phalanx write-artifact` with your results. Do not ask questions."
    )
    try:
        process_manager.send_keys(agent_id, nudge, enter=True)
        logger.info("Nudged idle agent %s", agent_id)
    except Exception as e:
        logger.warning("Failed to nudge agent %s: %s", agent_id, e)
