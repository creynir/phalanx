"""Team orchestration: status, stop, resume, result reading."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from phalanx.artifacts.reader import read_agent_artifact, read_team_artifact
from phalanx.artifacts.schema import Artifact
from phalanx.db import StateDB
from phalanx.monitor.heartbeat import HeartbeatMonitor
from phalanx.process.manager import ProcessManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resume context builder
# ---------------------------------------------------------------------------


def _build_resume_prompt(
    phalanx_root: Path,
    db: StateDB,
    agent: dict,
) -> str:
    """Build a context-enriched prompt for a resumed agent.

    Instead of replaying the original task.md (which gives the agent zero
    memory of its prior session), this injects:
      - The original task
      - The agent's own previous artifact (if any)
      - Team state: every worker's status and artifact summary
      - Any pending messages from the main agent

    The result overwrites task.md so the agent starts with full context.
    """
    team_id = agent["team_id"]
    agent_id = agent["id"]
    role = agent["role"]
    original_task = agent.get("task", "")

    soul_dir = Path(__file__).parent.parent / "soul"
    soul_map = {
        "lead": "team_lead.md",
        "worker": "worker.md",
        "engineering_manager": "engineering_manager.md",
    }
    soul_file = soul_dir / soul_map.get(role, "worker.md")

    # Fallback: check user-overridable soul dir
    user_soul_dir = phalanx_root / "soul"
    user_soul_file = user_soul_dir / soul_map.get(role, "worker.md")
    if user_soul_file.exists():
        soul_file = user_soul_file

    soul_content = ""
    if soul_file.exists():
        soul_content = soul_file.read_text(encoding="utf-8")

    all_agents = db.list_agents(team_id)

    if role == "lead":
        return _build_lead_resume(
            phalanx_root,
            team_id,
            agent_id,
            original_task,
            soul_content,
            all_agents,
        )
    elif role == "engineering_manager":
        return _build_engineering_manager_resume(
            phalanx_root,
            db,
            team_id,
            agent_id,
            original_task,
            soul_content,
            all_agents,
        )
    else:
        return _build_worker_resume(
            phalanx_root,
            team_id,
            agent_id,
            original_task,
            soul_content,
            all_agents,
            db=db,
        )


def _build_lead_resume(
    phalanx_root: Path,
    team_id: str,
    agent_id: str,
    original_task: str,
    soul_content: str,
    all_agents: list[dict],
) -> str:
    """Build resume prompt for a team lead."""
    workers = [a for a in all_agents if a["role"] != "lead"]

    # Build worker list with current statuses
    worker_lines = []
    for w in workers:
        line = f"- {w['id']} (role={w['role']}, status={w['status']}"
        art = read_agent_artifact(phalanx_root, team_id, w["id"])
        if art:
            line += f", artifact={art.status}"
        else:
            line += ", artifact=none"
        line += ")"
        worker_lines.append(line)
    worker_list_str = "\n".join(worker_lines) if worker_lines else "(no workers)"

    # Build worker artifact summaries
    artifact_sections = []
    for w in workers:
        art = read_agent_artifact(phalanx_root, team_id, w["id"])
        if art:
            output = art.output
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    pass
            artifact_sections.append(
                f"### {w['id']} (status: {art.status})\n```json\n"
                f"{json.dumps(output, indent=2, ensure_ascii=False)}\n```"
            )

    # Read pending messages from main agent
    msg_dir = phalanx_root / "teams" / team_id / "messages"
    pending_msgs = []
    if msg_dir.exists():
        for msg_file in sorted(msg_dir.iterdir()):
            if msg_file.name.startswith(f"msg_{agent_id}"):
                pending_msgs.append(msg_file.read_text(encoding="utf-8").strip())

    # Substitute soul template placeholder
    prompt = soul_content
    if "{task}" in prompt:
        prompt = prompt.replace("{task}", original_task)

    # Append resume context section
    resume_ctx = "\n\n---\n\n## RESUME CONTEXT — You are being resumed\n\n"
    resume_ctx += (
        "You were previously running this team and were suspended due to "
        "idle timeout. You are now being restarted. DO NOT repeat work "
        "that was already completed.\n\n"
    )
    resume_ctx += f"**Team ID:** {team_id}\n\n"
    resume_ctx += f"**Original task:** {original_task}\n\n"

    resume_ctx += "### Current Worker Status\n"
    resume_ctx += worker_list_str + "\n\n"

    if artifact_sections:
        resume_ctx += "### Worker Artifacts from Previous Round\n"
        resume_ctx += "\n\n".join(artifact_sections) + "\n\n"

    # Lead's own previous artifact
    lead_art = read_agent_artifact(phalanx_root, team_id, agent_id)
    if lead_art:
        output = lead_art.output
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                pass
        resume_ctx += (
            "### Your Previous Artifact\n"
            f"```json\n{json.dumps(output, indent=2, ensure_ascii=False)}\n```\n\n"
        )

    if pending_msgs:
        resume_ctx += "### Pending Messages\n"
        for i, msg in enumerate(pending_msgs, 1):
            resume_ctx += f"**Message {i}:**\n{msg}\n\n"

    resume_ctx += (
        "### Instructions\n"
        "1. Review the worker statuses and artifacts above.\n"
        "2. If there are pending messages, follow their instructions.\n"
        "3. Resume suspended/dead workers with `phalanx resume-agent <id>` "
        "ONLY if they need to do NEW work.\n"
        "4. Do NOT resume workers that already have successful artifacts "
        "unless you have new tasks for them.\n"
        "5. If all work is already complete, write your final team artifact.\n"
    )

    merged = (
        "Execute the following task immediately "
        "without summarising or asking questions:"
        f"\n\n{prompt}{resume_ctx}"
    )
    return merged


def _build_worker_resume(
    phalanx_root: Path,
    team_id: str,
    agent_id: str,
    original_task: str,
    soul_content: str,
    all_agents: list[dict],
    db: StateDB | None = None,
) -> str:
    """Build resume prompt for a worker agent.

    v1.0.0: If post-artifact feed messages exist (timestamps after the
    artifact's created_at), the agent is instructed to process the new
    directives instead of waiting idle.
    """
    prompt = soul_content
    if "{task}" in prompt:
        prompt = prompt.replace("{task}", original_task)

    art = read_agent_artifact(phalanx_root, team_id, agent_id)

    resume_ctx = "\n\n---\n\n## RESUME CONTEXT — You are being resumed\n\n"
    resume_ctx += "You were previously running and were suspended. You are now being restarted.\n\n"

    post_artifact_directives = _get_post_artifact_feed(db, team_id, art)

    if art:
        output = art.output
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                pass
        resume_ctx += (
            "### Your Previous Artifact\n"
            f"You already completed your original task and wrote this artifact:\n"
            f"```json\n{json.dumps(output, indent=2, ensure_ascii=False)}\n```\n\n"
        )

        if post_artifact_directives:
            resume_ctx += (
                "### NEW DIRECTIVES (Posted After Your Artifact)\n"
                "The following messages were posted to the team feed AFTER "
                "your artifact. Process these new directives and update your "
                "work accordingly. You may overwrite your previous artifact.\n\n"
            )
            for i, msg in enumerate(post_artifact_directives, 1):
                resume_ctx += f"**Directive {i}** (from {msg['sender_id']}):\n{msg['content']}\n\n"
        else:
            resume_ctx += (
                "**Do NOT redo this work.** Wait for a message from the team lead "
                "with your new assignment. Check for pending messages by reading "
                "any files referenced in prompts. If no new task arrives within "
                "30 seconds, run `phalanx feed` to check the team feed.\n"
            )
    else:
        resume_ctx += (
            "You did not complete your previous task. Pick up where you left off and complete it.\n"
        )

    merged = (
        "Execute the following task immediately "
        "without summarising or asking questions:"
        f"\n\n{prompt}{resume_ctx}"
    )
    return merged


def _build_engineering_manager_resume(
    phalanx_root: Path,
    db: StateDB,
    team_id: str,
    agent_id: str,
    original_task: str,
    soul_content: str,
    all_agents: list[dict],
) -> str:
    """Build resume prompt for an engineering manager (outer loop) agent.

    Injects full team state, all artifacts, event log summary,
    and escalation context.
    """
    prompt = soul_content
    if "{task}" in prompt:
        prompt = prompt.replace("{task}", original_task)

    resume_ctx = "\n\n---\n\n## RESUME CONTEXT — Engineering Manager Activation\n\n"
    resume_ctx += (
        "You are being activated because the Middle Loop could not resolve "
        "a systemic issue. Analyze the state below and emit an EngineeringManagerDecision.\n\n"
    )

    resume_ctx += f"**Team ID:** {team_id}\n\n"

    # Full agent state
    resume_ctx += "### All Agent Statuses\n"
    for a in all_agents:
        line = f"- {a['id']} (role={a['role']}, status={a['status']}"
        line += f", backend={a.get('backend', '?')}, model={a.get('model', '?')}"
        line += f", attempts={a.get('attempts', 0)}"
        art = read_agent_artifact(phalanx_root, team_id, a["id"])
        if art:
            line += f", artifact={art.status}"
        else:
            line += ", artifact=none"
        line += ")"
        resume_ctx += line + "\n"

    # All artifacts
    resume_ctx += "\n### Agent Artifacts\n"
    for a in all_agents:
        art = read_agent_artifact(phalanx_root, team_id, a["id"])
        if art:
            output = art.output
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    pass
            resume_ctx += (
                f"#### {a['id']} ({a['role']}, artifact={art.status})\n"
                f"```json\n{json.dumps(output, indent=2, ensure_ascii=False)[:3000]}\n```\n\n"
            )

    # Event log summary
    try:
        events = db.get_recent_events(team_id, limit=30)
        if events:
            resume_ctx += "### Recent Events (newest first)\n"
            for r in events:
                resume_ctx += (
                    f"- {r['event_type']}"
                    f" agent={r.get('agent_id', 'N/A')}"
                    f" payload={r.get('payload', '')}\n"
                )
            resume_ctx += "\n"
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to get recent events: %s", e)

    # Escalation context from feed
    try:
        recent_feed = db.get_feed(team_id, limit=20)
        escalation_msgs = [
            m
            for m in recent_feed
            if "[ESCALATION]" in m.get("content", "")
            or "escalation" in m.get("content", "").lower()
        ]
        if escalation_msgs:
            resume_ctx += "### Escalation Messages\n"
            for m in escalation_msgs:
                resume_ctx += f"- From {m['sender_id']}: {m['content']}\n"
            resume_ctx += "\n"
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to get recent events: %s", e)

    resume_ctx += (
        "### Instructions\n"
        "1. Analyze the team state, event log, and escalation context above.\n"
        "2. Identify the root cause of the issue.\n"
        "3. Select the least disruptive action that resolves the problem.\n"
        "4. Write your artifact with the EngineeringManagerDecision JSON.\n"
    )

    merged = (
        "Execute the following task immediately "
        "without summarising or asking questions:"
        f"\n\n{prompt}{resume_ctx}"
    )
    return merged


def _get_post_artifact_feed(
    db: "StateDB | None",
    team_id: str,
    artifact: "Artifact | None",
) -> list[dict]:
    """Return feed messages posted after the artifact's created_at timestamp."""
    if db is None or artifact is None:
        return []
    try:
        return db.get_feed(team_id, limit=50, since=artifact.created_at)
    except Exception:
        return []


def get_team_status(db: StateDB, team_id: str) -> dict | None:
    """Get comprehensive team status including all agents and cost summary."""
    from phalanx.costs.aggregator import CostAggregator

    team = db.get_team(team_id)
    if team is None:
        return None

    agents = db.list_agents(team_id)

    try:
        aggregator = CostAggregator(db)
        cost_breakdown = aggregator.get_team_costs(team_id)
        cost_summary = {
            "total_tokens": cost_breakdown.total_tokens,
            "input_tokens": cost_breakdown.total_input_tokens,
            "output_tokens": cost_breakdown.total_output_tokens,
            "estimated_cost": cost_breakdown.total_estimated_cost,
        }
    except Exception:
        cost_summary = None

    return {
        "team": team,
        "agents": agents,
        "agent_count": len(agents),
        "running_count": sum(1 for a in agents if a["status"] == "running"),
        "costs": cost_summary,
    }


def stop_team(
    db: StateDB,
    process_manager: ProcessManager,
    team_id: str,
) -> dict:
    """Stop all agents in a team and the team monitor. Data is preserved for resuming."""
    agents = db.list_agents(team_id)
    stopped = []
    for agent in agents:
        if agent["status"] in ("running", "pending", "blocked_on_prompt"):
            process_manager.kill_agent(agent["id"])
            db.update_agent(agent["id"], status="dead")
            stopped.append(agent["id"])

    _kill_team_monitor(team_id)

    db.update_team_status(team_id, "dead")
    logger.info("Stopped team %s (%d agents killed)", team_id, len(stopped))
    return {"team_id": team_id, "stopped_agents": stopped}


def resume_team(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    team_id: str,
    resume_all: bool = True,
    auto_approve: bool = False,
) -> dict:
    """Resume a dead/stopped team by restarting all dead/suspended agents.

    By default restarts ALL dead/suspended agents. Set resume_all=False to
    restart only the team lead (legacy behaviour, not recommended).
    """
    from phalanx.backends import get_backend
    from phalanx.team.create import _spawn_team_monitor

    agents = db.list_agents(team_id)
    resumed = []

    for agent in agents:
        if agent["status"] not in ("dead", "suspended"):
            continue

        is_lead = agent["role"] == "lead"
        if not is_lead and not resume_all:
            continue

        agent_id = agent["id"]
        backend = get_backend(agent.get("backend", "cursor"))

        agent_proc = _resume_agent_with_context(
            phalanx_root,
            db,
            process_manager,
            agent,
            backend,
            auto_approve,
        )
        if agent_proc is None:
            continue

        db.update_agent(agent_id, status="running")
        heartbeat_monitor.register(agent_id, agent_proc.stream_log)
        resumed.append(agent_id)

        logger.info("Resumed agent %s in team %s", agent_id, team_id)

    if resumed:
        db.update_team_status(team_id, "running")
        _spawn_team_monitor(phalanx_root, team_id)

    return {"team_id": team_id, "resumed_agents": resumed}


def resume_single_agent(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    heartbeat_monitor: HeartbeatMonitor,
    agent_id: str,
    auto_approve: bool = False,
) -> dict:
    """Resume a single dead/suspended agent within its team."""
    from phalanx.backends import get_backend

    agent = db.get_agent(agent_id)
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found")

    if agent["status"] not in ("dead", "suspended"):
        raise ValueError(f"Agent {agent_id} is {agent['status']}, not dead/suspended")

    team_id = agent["team_id"]
    backend = get_backend(agent.get("backend", "cursor"))

    agent_proc = _resume_agent_with_context(
        phalanx_root,
        db,
        process_manager,
        agent,
        backend,
        auto_approve,
    )
    if agent_proc is None:
        raise ValueError(f"Cannot resume agent {agent_id}: no task in DB and no task.md on disk")

    db.update_agent(agent_id, status="running")
    heartbeat_monitor.register(agent_id, agent_proc.stream_log)
    logger.info("Resumed agent %s in team %s", agent_id, team_id)

    return {"agent_id": agent_id, "team_id": team_id, "status": "running"}


def _resume_agent_with_context(
    phalanx_root: Path,
    db: StateDB,
    process_manager: ProcessManager,
    agent: dict,
    backend,
    auto_approve: bool,
):
    """Resume an agent with a context-enriched prompt.

    Returns the AgentProcess on success, or None if the agent can't be resumed.
    """
    agent_id = agent["id"]
    team_id = agent["team_id"]
    chat_id = agent.get("chat_id")

    if chat_id:
        return process_manager.spawn_resume(
            team_id=team_id,
            agent_id=agent_id,
            backend=backend,
            chat_id=chat_id,
            auto_approve=auto_approve,
        )

    # Build context-enriched resume prompt
    resume_prompt = _build_resume_prompt(phalanx_root, db, agent)

    task_file = phalanx_root / "teams" / team_id / "agents" / agent_id / "task.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(resume_prompt, encoding="utf-8")

    return process_manager.spawn(
        team_id=team_id,
        agent_id=agent_id,
        backend=backend,
        prompt=str(task_file),
        soul_file=None,  # soul is already in the resume prompt
        model=agent.get("model"),
        auto_approve=auto_approve,
    )


def _kill_team_monitor(team_id: str) -> None:
    """Kill the team monitor tmux session if it exists."""
    try:
        import libtmux

        server = libtmux.Server()
        session_name = f"phalanx-mon-{team_id}"
        session = server.sessions.get(session_name=session_name)
        session.kill()
        logger.info("Killed team monitor session %s", session_name)
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to get recent events: %s", e)


def get_team_result(phalanx_root: Path, team_id: str) -> dict | None:
    """Read the team lead's artifact."""
    # Primary path: resolve actual lead agent id from DB and read its artifact
    # from teams/<team>/agents/<lead-id>/artifact.json.
    try:
        db = StateDB(phalanx_root / "state.db")
        agents = db.list_agents(team_id)
        lead = next((a for a in agents if a.get("role") == "lead"), None)
        if lead:
            artifact = read_agent_artifact(phalanx_root, team_id, lead["id"])
            if artifact:
                return artifact.to_dict()
    except Exception:
        # Keep compatibility fallback below if DB lookup fails.
        pass

    # Backward compatibility: legacy location teams/<team>/lead/artifact.json.
    artifact = read_team_artifact(phalanx_root, team_id)
    if artifact:
        return artifact.to_dict()
    return None


def get_agent_result(phalanx_root: Path, team_id: str, agent_id: str) -> dict | None:
    """Read a specific agent's artifact."""
    artifact = read_agent_artifact(phalanx_root, team_id, agent_id)
    if artifact:
        return artifact.to_dict()
    return None
