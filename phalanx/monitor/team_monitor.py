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
) -> None:
    """Blocking loop that monitors all agents in a team.

    Runs until all agents are in a terminal state (dead/suspended/failed).
    """
    logger.info("Team monitor started for %s (poll=%ds)", team_id, poll_interval)

    while True:
        agents = db.list_agents(team_id)
        if not agents:
            logger.info("No agents found for team %s, exiting monitor", team_id)
            break

        active_count = 0
        for agent in agents:
            if agent["status"] in ("dead", "failed", "suspended"):
                continue

            agent_id = agent["id"]
            active_count += 1

            event = stall_detector.check_agent(agent_id)

            # Persist heartbeat to DB (stall_detector already called hb.check internally)
            if heartbeat_monitor.get_state(agent_id) is not None:
                db.update_heartbeat(agent_id)
            if event is None:
                continue

            if event.state == AgentState.DEAD:
                logger.warning("Agent %s is dead (tmux gone)", agent_id)
                db.update_agent(agent_id, status="dead")
                db.log_event(team_id, "agent_dead", agent_id=agent_id)

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

                # For agent_idle (parked at prompt without artifact), send an
                # automatic nudge so the agent executes its task without needing
                # the team lead to intervene.
                if event.prompt_type == "agent_idle":
                    _nudge_idle_agent(process_manager, agent_id)

        if active_count == 0:
            logger.info("All agents in team %s are in terminal state", team_id)
            db.update_team_status(team_id, "dead")
            db.log_event(team_id, "team_dead")
            break

        time.sleep(poll_interval)

    logger.info("Team monitor for %s exiting", team_id)


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
