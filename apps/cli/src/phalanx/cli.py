"""Phalanx CLI — entry point for multi-agent orchestration.

Subcommands:
  create-team   Create a team (--config for per-agent prompts)
  team-monitor  Per-team monitoring daemon (auto-spawned)
  monitor       Blocking DEM-style monitor loop for single agent
  team-status   Show team status
  agent-status  Show agent status
  team-result   Read team lead's artifact
  agent-result  Read agent's artifact
  message       Send message to team lead
  message-agent Send message to specific agent
  broadcast     Send message to all agents in a team
  post          Post to team feed
  feed          Read team feed
  send-keys     Send raw keystrokes to an agent
  resume        Resume a stopped/dead team
  stop          Stop a team
  stop-agent    Stop a specific agent
  write-artifact Write structured artifact
  lock          Acquire file lock
  unlock        Release file lock
  lock-status   Show file locks
  list-teams    List all teams
  status        Show all running agents
  init          Initialize .phalanx/ in workspace
  gc            Run garbage collection
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import click

from phalanx import __version__
from phalanx.config import PhalanxConfig, load_config, save_config
from phalanx.db import StateDB

logger = logging.getLogger(__name__)

PHALANX_ROOT_DEFAULT = ".phalanx"


def _get_root(ctx: click.Context) -> Path:
    return Path(ctx.obj.get("root", PHALANX_ROOT_DEFAULT)).resolve()


def _get_db(root: Path) -> StateDB:
    return StateDB(root / "state.db")


def _get_config(root: Path) -> PhalanxConfig:
    return load_config(root)


def _json_output(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ── Main group ───────────────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="phalanx")
@click.option(
    "--root",
    envvar="PHALANX_ROOT",
    default=PHALANX_ROOT_DEFAULT,
    help="Path to .phalanx directory",
)
@click.option("--json-output", "json_mode", is_flag=True, help="JSON output mode")
@click.option(
    "--auto-approve", is_flag=True, default=False, help="Enable auto-approve for all spawned agents"
)
@click.option("--backend", "-b", default=None, help="Backend (cursor, claude, gemini, codex)")
@click.option("--model", "-m", default=None, help="Model to use for the agent")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
@click.pass_context
def cli(ctx, root, json_mode, auto_approve, backend, model, verbose):
    """Phalanx — Multi-Agent Orchestration System.

    Run without a subcommand to launch your agent with phalanx skills:

      phalanx --auto-approve --backend cursor --model opus-4.6-thinking
    """
    ctx.ensure_object(dict)
    ctx.obj["root"] = root
    ctx.obj["json_mode"] = json_mode
    ctx.obj["auto_approve"] = auto_approve
    ctx.obj["backend"] = backend
    ctx.obj["model"] = model

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if ctx.invoked_subcommand is None:
        _launch_agent(ctx, backend, model, auto_approve)


# ── default: launch agent ────────────────────────────────────────────


def _launch_agent(
    ctx: click.Context, backend: str | None, model: str | None, auto_approve: bool
) -> None:
    """Launch the backend agent CLI with phalanx skills installed.

    1. Resolve backend (flag → config → auto-detect)
    2. Run phalanx init if needed (creates .phalanx/, deploys skills)
    3. Check/update skills for the backend
    4. exec the backend binary, replacing this process
    """
    from phalanx.backends.registry import get_backend, detect_backend
    from phalanx.init_cmd import check_and_prompt_skill, init_workspace

    root = _get_root(ctx)

    # Auto-init if .phalanx doesn't exist yet
    if not root.exists():
        workspace = root.parent if root.name == ".phalanx" else Path.cwd()
        click.echo("Initializing phalanx...")
        init_workspace(workspace)
        root.mkdir(parents=True, exist_ok=True)

    config = _get_config(root)
    backend_name = backend or config.default_backend

    # Resolve backend
    if backend_name:
        be = get_backend(backend_name)
    else:
        be = detect_backend()
        if be is None:
            click.echo(
                "Error: No agent CLI found. Install one of: cursor (agent), claude, gemini, codex",
                err=True,
            )
            raise SystemExit(1)
        backend_name = be.name()

    # Ensure skills are installed/up-to-date
    check_and_prompt_skill(backend_name, workspace=Path.cwd())

    # Build the command
    binary = be.binary_name()
    cmd = [binary]

    if auto_approve:
        cmd.extend(be.auto_approve_flags())

    if model or config.default_model:
        cmd.extend(["--model", model or config.default_model])

    click.echo(f"Launching {backend_name} agent...")
    os.execvp(binary, cmd)


# ── create-team ──────────────────────────────────────────────────────


@cli.command("create-team")
@click.argument("task", required=False, default=None)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=True),
    help="JSON config file with per-agent prompts",
)
@click.option("--agents", "-a", default="coder", help="Agent spec: role[:count],...")
@click.option("--backend", "-b", default=None, help="Backend")
@click.option("--model", "-m", default=None, help="Model")
@click.option(
    "--idle-timeout", type=int, default=None, help="Idle timeout in seconds (default: 1800)"
)
@click.option(
    "--max-runtime", type=int, default=None, help="Max runtime in seconds (default: 1800)"
)
@click.option("--worktree", is_flag=True, help="Create a git worktree for the team")
@click.pass_context
def create_team_cmd(
    ctx, task, config_path, agents, backend, model, idle_timeout, max_runtime, worktree=False
):
    """Create a team with per-agent prompts (--config) or simple shared task."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    phalanx_config = _get_config(root)
    db = _get_db(root)
    backend_name = backend or phalanx_config.default_backend
    auto_approve = ctx.obj.get("auto_approve", False)

    effective_idle = idle_timeout or phalanx_config.idle_timeout_seconds
    effective_max_runtime = max_runtime or phalanx_config.max_runtime_seconds

    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=effective_idle)

    if config_path:
        from phalanx.team.config import load_team_config
        from phalanx.team.create import create_team_from_config

        team_config = load_team_config(Path(config_path))
        team_id, lead_id, worker_ids = create_team_from_config(
            phalanx_root=root,
            db=db,
            process_manager=pm,
            heartbeat_monitor=hb,
            team_config=team_config,
            backend_name=backend_name,
            auto_approve=auto_approve,
            config=phalanx_config,
            idle_timeout=effective_idle,
            max_runtime=effective_max_runtime,
        )
        result = {
            "ok": True,
            "team_id": team_id,
            "lead_id": lead_id,
            "worker_ids": worker_ids,
        }
    else:
        if not task:
            click.echo("Error: TASK argument is required when --config is not provided", err=True)
            raise SystemExit(1)

        from phalanx.team.create import create_team

        team_id, lead_id = create_team(
            phalanx_root=root,
            db=db,
            process_manager=pm,
            heartbeat_monitor=hb,
            task=task,
            agents_spec=agents,
            backend_name=backend_name,
            model=model or phalanx_config.default_model,
            auto_approve=auto_approve,
            config=phalanx_config,
            idle_timeout=effective_idle,
            max_runtime=effective_max_runtime,
            worktree=worktree,
        )
        result = {"ok": True, "team_id": team_id, "lead_id": lead_id}

    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(f"Team created: {result['team_id']}")
        click.echo(f"  Lead: {result['lead_id']}")
        if "worker_ids" in result:
            for wid in result["worker_ids"]:
                click.echo(f"  Worker: {wid}")


# ── monitor / team-monitor ───────────────────────────────────────────


@cli.command("monitor")
@click.argument("agent_id")
@click.option("--team-id", envvar="PHALANX_TEAM_ID", default=None)
@click.pass_context
def monitor_cmd(ctx, agent_id, team_id):
    """Blocking DEM-style monitoring loop for an agent."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.lifecycle import run_monitor_loop
    from phalanx.monitor.stall import StallDetector
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    config = _get_config(root)
    db = _get_db(root)

    agent = db.get_agent(agent_id)
    if agent is None:
        click.echo(f"Error: Agent '{agent_id}' not found", err=True)
        raise SystemExit(1)

    resolved_team_id = team_id or agent["team_id"]
    stream_log = root / "teams" / resolved_team_id / "agents" / agent_id / "stream.log"

    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=config.idle_timeout_seconds)
    hb.register(agent_id, stream_log)
    sd = StallDetector(pm, hb, idle_timeout=config.idle_timeout_seconds, db=db)

    click.echo(f"Monitoring agent {agent_id}...")
    result = run_monitor_loop(
        agent_id=agent_id,
        process_manager=pm,
        heartbeat_monitor=hb,
        stall_detector=sd,
        max_retries=config.max_retries,
        max_runtime=config.max_runtime_seconds,
        poll_interval=config.monitor_poll_interval,
    )

    if ctx.obj.get("json_mode"):
        _json_output(result.to_dict())
    else:
        click.echo(json.dumps(result.to_dict(), indent=2))


@cli.command("team-monitor")
@click.argument("team_id")
@click.option("--idle-timeout", type=int, default=None, help="Idle timeout in seconds")
@click.option("--max-runtime", type=int, default=None, help="Max runtime in seconds")
@click.pass_context
def team_monitor_cmd(ctx, team_id, idle_timeout, max_runtime):
    """Per-team monitoring daemon. Auto-spawned by create-team in tmux."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector
    from phalanx.monitor.team_monitor import run_team_monitor
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    config = _get_config(root)
    db = _get_db(root)

    effective_idle = idle_timeout or config.idle_timeout_seconds
    effective_max_runtime = max_runtime or config.max_runtime_seconds

    team = db.get_team(team_id)
    if team is None:
        click.echo(f"Error: Team '{team_id}' not found", err=True)
        raise SystemExit(1)

    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=effective_idle)

    agents = db.list_agents(team_id)
    for agent in agents:
        stream_log = root / "teams" / team_id / "agents" / agent["id"] / "stream.log"
        if stream_log.exists() or stream_log.parent.exists():
            hb.register(agent["id"], stream_log)
        pm.discover_agent(team_id, agent["id"])

    sd = StallDetector(pm, hb, idle_timeout=effective_idle, db=db)

    lead_agents = [a for a in agents if a.get("role") == "lead"]
    lead_agent_id = lead_agents[0]["id"] if lead_agents else None
    message_dir = root / "teams" / team_id / "messages"

    from phalanx.costs.aggregator import CostAggregator

    cost_aggregator = CostAggregator(db)

    click.echo(
        f"Team monitor started for {team_id} ({len(agents)} agents, "
        f"idle={effective_idle}s, max_runtime={effective_max_runtime}s)"
    )
    run_team_monitor(
        team_id=team_id,
        db=db,
        process_manager=pm,
        heartbeat_monitor=hb,
        stall_detector=sd,
        poll_interval=config.monitor_poll_interval,
        idle_timeout=effective_idle,
        lead_agent_id=lead_agent_id,
        message_dir=message_dir,
        phalanx_root=root,
        cost_aggregator=cost_aggregator,
    )


# ── team-status / agent-status ──────────────────────────────────────


@cli.command("team-status")
@click.argument("team_id", required=False, default=None)
@click.pass_context
def team_status_cmd(ctx, team_id):
    """Show team status."""
    root = _get_root(ctx)
    db = _get_db(root)

    if team_id:
        from phalanx.team.orchestrator import get_team_status

        result = get_team_status(db, team_id)
        if result is None:
            click.echo(f"Team '{team_id}' not found", err=True)
            raise SystemExit(1)
    else:
        teams = db.list_teams()
        result = {"teams": teams, "count": len(teams)}

    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(json.dumps(result, indent=2, default=str))


@cli.command("agent-status")
@click.argument("agent_id", required=False, default=None)
@click.pass_context
def agent_status_cmd(ctx, agent_id):
    """Show agent status."""
    root = _get_root(ctx)
    db = _get_db(root)

    if agent_id:
        agent = db.get_agent(agent_id)
        if agent is None:
            click.echo(f"Agent '{agent_id}' not found", err=True)
            raise SystemExit(1)
        result = agent
    else:
        result = {"agents": db.list_agents()}

    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(json.dumps(result, indent=2, default=str))


# ── team-result / agent-result ──────────────────────────────────────


@cli.command("team-result")
@click.argument("team_id")
@click.pass_context
def team_result_cmd(ctx, team_id):
    """Read team lead's artifact."""
    from phalanx.team.orchestrator import get_team_result

    root = _get_root(ctx)
    result = get_team_result(root, team_id)
    if result is None:
        click.echo(f"No artifact found for team '{team_id}'", err=True)
        raise SystemExit(1)
    _json_output(result)


@cli.command("agent-result")
@click.argument("agent_id")
@click.option("--team-id", envvar="PHALANX_TEAM_ID", required=True)
@click.pass_context
def agent_result_cmd(ctx, agent_id, team_id):
    """Read agent's artifact."""
    from phalanx.team.orchestrator import get_agent_result

    root = _get_root(ctx)
    result = get_agent_result(root, team_id, agent_id)
    if result is None:
        click.echo(f"No artifact found for agent '{agent_id}'", err=True)
        raise SystemExit(1)
    _json_output(result)


# ── team-costs / team-debt ───────────────────────────────────────────


@cli.command("team-costs")
@click.argument("team_id")
@click.pass_context
def team_costs_cmd(ctx, team_id):
    """Show token usage and estimated cost breakdown for a team."""
    from phalanx.costs.aggregator import CostAggregator

    root = _get_root(ctx)
    phalanx_config = _get_config(root)
    db = _get_db(root)

    cost_table = getattr(phalanx_config, "cost_table", None)
    aggregator = CostAggregator(db, cost_table=cost_table)
    breakdown = aggregator.get_team_costs(team_id)

    if ctx.obj.get("json_mode"):
        _json_output(breakdown.to_dict())
    else:
        click.echo(f"Team {team_id} Cost Breakdown:")
        click.echo(f"  Total tokens: {breakdown.total_tokens}")
        click.echo(f"  Input tokens: {breakdown.total_input_tokens}")
        click.echo(f"  Output tokens: {breakdown.total_output_tokens}")
        if breakdown.total_estimated_cost is not None:
            click.echo(f"  Estimated cost: ${breakdown.total_estimated_cost:.4f}")
        else:
            click.echo("  Estimated cost: N/A")
        if breakdown.by_role:
            click.echo("  By role:")
            for role, data in breakdown.by_role.items():
                click.echo(
                    f"    {role}: {data['input_tokens']}in/{data['output_tokens']}out ${data.get('cost', 0):.4f}"
                )


@cli.command("team-debt")
@click.argument("team_id")
@click.pass_context
def team_debt_cmd(ctx, team_id):
    """Show typed debt/compromise records for a team."""
    root = _get_root(ctx)
    db = _get_db(root)
    records = db.get_team_debt(team_id)

    if ctx.obj.get("json_mode"):
        _json_output({"team_id": team_id, "debt_records": records, "count": len(records)})
    else:
        if not records:
            click.echo(f"No debt records for team {team_id}")
        else:
            click.echo(f"Team {team_id} Debt Records ({len(records)}):")
            for r in records:
                click.echo(f"  [{r['severity'].upper()}] {r['category']}: {r['description'][:80]}")


# ── message / message-agent / broadcast ─────────────────────────────


@cli.command("message")
@click.argument("team_id")
@click.argument("text")
@click.pass_context
def message_cmd(ctx, team_id, text):
    """Send message to team lead via send-keys."""
    from phalanx.comms.messaging import deliver_message
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    db = _get_db(root)

    agents = db.list_agents(team_id)
    lead = next((a for a in agents if a["role"] == "lead"), None)

    if lead is None:
        click.echo(f"Error: No team lead found for team '{team_id}'", err=True)
        raise SystemExit(1)

    if lead["status"] != "running":
        status = lead["status"]
        click.echo(
            f"Error: Team lead is {status} — message not delivered.\n"
            f"Use 'phalanx resume {team_id}' to restart it.",
            err=True,
        )
        if ctx.obj.get("json_mode"):
            _json_output(
                {"ok": False, "team_id": team_id, "delivered": False, "lead_status": status}
            )
        raise SystemExit(1)

    pm = ProcessManager(root)
    delivered = deliver_message(pm, lead["id"], text)

    if ctx.obj.get("json_mode"):
        _json_output({"ok": delivered, "team_id": team_id, "delivered": delivered})
    else:
        click.echo(f"Message delivered to team lead ({lead['id']})")


@cli.command("message-agent")
@click.argument("agent_id")
@click.argument("text")
@click.pass_context
def message_agent_cmd(ctx, agent_id, text):
    """Send message to a specific agent via send-keys.

    Works for agents in 'running' or 'blocked_on_prompt' state.
    For blocked agents, the message is sent as raw keystrokes to unblock them.
    """
    from phalanx.comms.messaging import deliver_message
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    db = _get_db(root)

    agent = db.get_agent(agent_id)
    if agent is None:
        click.echo(f"Agent '{agent_id}' not found", err=True)
        raise SystemExit(1)

    status = agent["status"]
    # Allow delivery to running AND blocked_on_prompt agents — both have a live tmux pane.
    if status not in ("running", "blocked_on_prompt"):
        click.echo(
            f"Error: Agent {agent_id} is {status} — message not delivered.\n"
            f"Use 'phalanx resume-agent {agent_id}' to restart it.",
            err=True,
        )
        if ctx.obj.get("json_mode"):
            _json_output({"ok": False, "agent_id": agent_id, "delivered": False, "status": status})
        raise SystemExit(1)

    pm = ProcessManager(root)
    delivered = deliver_message(pm, agent_id, text)

    if status == "blocked_on_prompt" and delivered:
        # The keystroke may have unblocked the agent; update its status to running.
        db.update_agent(agent_id, status="running")

    if ctx.obj.get("json_mode"):
        _json_output({"ok": delivered, "agent_id": agent_id, "delivered": delivered})
    else:
        click.echo(f"Message delivered to agent {agent_id}")


@cli.command("broadcast")
@click.argument("team_id")
@click.argument("text")
@click.pass_context
def broadcast_cmd(ctx, team_id, text):
    """Broadcast a message to all agents in a team via send-keys."""
    from phalanx.comms.messaging import broadcast_message
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    db = _get_db(root)
    pm = ProcessManager(root)

    agents = {a["id"]: a for a in db.list_agents(team_id)}
    results = broadcast_message(pm, db, team_id, text)

    delivered = sum(1 for v in results.values() if v)
    skipped = {
        aid: agents[aid]["status"] for aid, ok in results.items() if not ok and aid in agents
    }

    if ctx.obj.get("json_mode"):
        _json_output(
            {
                "ok": delivered > 0,
                "team_id": team_id,
                "delivered": delivered,
                "total": len(results),
                "results": results,
                "skipped": skipped,
            }
        )
    else:
        click.echo(f"Broadcast to team {team_id}: {delivered}/{len(results)} delivered")
        if skipped:
            skipped_list = ", ".join(f"{aid} ({st})" for aid, st in skipped.items())
            click.echo(f"  Skipped: {skipped_list}")


# ── post / feed (team communication) ─────────────────────────────────


@cli.command("post")
@click.argument("text")
@click.option("--team-id", envvar="PHALANX_TEAM_ID", required=True)
@click.pass_context
def post_cmd(ctx, text, team_id):
    """Post a message to the team feed (used by agents)."""
    root = _get_root(ctx)
    db = _get_db(root)

    sender_id = os.environ.get("PHALANX_AGENT_ID", "external")
    msg_id = db.post_to_feed(team_id, sender_id, text)

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "message_id": msg_id, "team_id": team_id})
    else:
        click.echo(f"Posted to team {team_id} feed")


@cli.command("feed")
@click.option("--team-id", envvar="PHALANX_TEAM_ID", required=True)
@click.option("--limit", default=50, help="Max messages to show")
@click.option("--since", default=None, help="Minutes ago (e.g., 5)")
@click.pass_context
def feed_cmd(ctx, team_id, limit, since):
    """Read the team feed (shared message log)."""
    import time as _time

    root = _get_root(ctx)
    db = _get_db(root)

    since_ts = None
    if since:
        since_ts = _time.time() - (int(since) * 60)

    messages = db.get_feed(team_id, limit=limit, since=since_ts)

    if ctx.obj.get("json_mode"):
        _json_output({"team_id": team_id, "messages": messages, "count": len(messages)})
    else:
        if not messages:
            click.echo("No messages in feed")
        else:
            for msg in messages:
                from datetime import datetime

                ts = datetime.fromtimestamp(msg["created_at"]).strftime("%H:%M:%S")
                click.echo(f"  [{ts}] {msg['sender_id']}: {msg['content'][:200]}")


# ── send-keys ────────────────────────────────────────────────────────


@cli.command("send-keys")
@click.argument("agent_id")
@click.argument("keys")
@click.option("--no-enter", is_flag=True, help="Don't press Enter after keys")
@click.pass_context
def send_keys_cmd(ctx, agent_id, keys, no_enter):
    """Send raw keystrokes to an agent's tmux pane.

    Used to resolve prompts (e.g., 'a' for workspace trust, 'y' for approval).
    Special keys: C-c (Ctrl+C), Enter, Tab, etc.
    """
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    pm = ProcessManager(root)

    success = pm.send_keys(agent_id, keys, enter=not no_enter)
    if ctx.obj.get("json_mode"):
        _json_output({"ok": success, "agent_id": agent_id, "keys": keys})
    else:
        if success:
            click.echo(f"Keys sent to {agent_id}: {keys!r}")
        else:
            click.echo(f"Failed to send keys to {agent_id}", err=True)
            raise SystemExit(1)


# ── resume ───────────────────────────────────────────────────────────


@cli.command("resume")
@click.argument("team_id")
@click.option(
    "--lead-only",
    is_flag=True,
    default=False,
    help="Resume only the team lead, leaving other agents dead",
)
@click.pass_context
def resume_cmd(ctx, team_id, lead_only):
    """Resume a stopped/dead team by restarting all dead/suspended agents."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager
    from phalanx.team.orchestrator import resume_team

    root = _get_root(ctx)
    phalanx_config = _get_config(root)
    db = _get_db(root)

    team = db.get_team(team_id)
    if team is None:
        click.echo(f"Error: Team '{team_id}' not found", err=True)
        raise SystemExit(1)

    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=phalanx_config.idle_timeout_seconds)

    result = resume_team(
        phalanx_root=root,
        db=db,
        process_manager=pm,
        heartbeat_monitor=hb,
        team_id=team_id,
        resume_all=not lead_only,
        auto_approve=ctx.obj.get("auto_approve", False),
    )

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, **result})
    else:
        click.echo(f"Team {team_id} resumed")
        for agent_id in result.get("resumed_agents", []):
            click.echo(f"  Resumed: {agent_id}")


# ── resume-agent ────────────────────────────────────────────────────


@cli.command("resume-agent")
@click.argument("agent_id")
@click.option(
    "--reply",
    default=None,
    help="Reply to send as keystrokes when agent is blocked_on_prompt (e.g. 'y')",
)
@click.pass_context
def resume_agent_cmd(ctx, agent_id, reply):
    """Resume a single dead/suspended agent, or unblock a blocked_on_prompt agent.

    Use --reply to send a keystroke reply to an agent waiting on a prompt.
    Example: phalanx resume-agent <id> --reply y
    """
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager
    from phalanx.team.orchestrator import resume_single_agent

    root = _get_root(ctx)
    phalanx_config = _get_config(root)
    db = _get_db(root)
    pm = ProcessManager(root)

    agent = db.get_agent(agent_id)
    if agent is None:
        if ctx.obj.get("json_mode"):
            _json_output({"ok": False, "error": f"Agent {agent_id} not found"})
        else:
            click.echo(f"Error: Agent {agent_id} not found", err=True)
        raise SystemExit(1)

    # Handle blocked_on_prompt: send reply keystrokes instead of restarting
    if agent["status"] == "blocked_on_prompt":
        if reply is None:
            click.echo(
                f"Error: Agent {agent_id} is blocked_on_prompt.\n"
                f"Use --reply to send a response (e.g. --reply y).",
                err=True,
            )
            if ctx.obj.get("json_mode"):
                _json_output(
                    {
                        "ok": False,
                        "agent_id": agent_id,
                        "status": "blocked_on_prompt",
                        "hint": "Use --reply <text> to unblock",
                    }
                )
            raise SystemExit(1)

        success = pm.send_keys(agent_id, reply, enter=True)
        if success:
            db.update_agent(agent_id, status="running")
        result = {
            "agent_id": agent_id,
            "team_id": agent["team_id"],
            "status": "running" if success else "blocked_on_prompt",
            "unblocked": success,
        }
        if ctx.obj.get("json_mode"):
            _json_output({"ok": success, **result})
        else:
            if success:
                click.echo(f"Agent {agent_id} unblocked (replied: {reply!r})")
            else:
                click.echo(f"Failed to send reply to agent {agent_id}", err=True)
                raise SystemExit(1)
        return

    hb = HeartbeatMonitor(idle_timeout=phalanx_config.idle_timeout_seconds)

    try:
        result = resume_single_agent(
            phalanx_root=root,
            db=db,
            process_manager=pm,
            heartbeat_monitor=hb,
            agent_id=agent_id,
            auto_approve=ctx.obj.get("auto_approve", False),
        )
    except ValueError as e:
        if ctx.obj.get("json_mode"):
            _json_output({"ok": False, "error": str(e)})
        else:
            click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, **result})
    else:
        click.echo(f"Agent {agent_id} resumed (team {result['team_id']})")


# ── stop / stop-agent ───────────────────────────────────────────────


@cli.command("stop")
@click.argument("team_id")
@click.pass_context
def stop_cmd(ctx, team_id):
    """Stop a team (kill processes, keep data, resumable)."""
    from phalanx.process.manager import ProcessManager
    from phalanx.team.orchestrator import stop_team

    root = _get_root(ctx)
    db = _get_db(root)
    pm = ProcessManager(root)

    result = stop_team(db, pm, team_id)
    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, **result})
    else:
        click.echo(f"Team {team_id} stopped ({len(result['stopped_agents'])} agents killed)")


@cli.command("stop-agent")
@click.argument("agent_id")
@click.pass_context
def stop_agent_cmd(ctx, agent_id):
    """Stop a specific agent."""
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    db = _get_db(root)
    pm = ProcessManager(root)

    pm.kill_agent(agent_id)
    db.update_agent(agent_id, status="dead")

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "agent_id": agent_id, "status": "dead"})
    else:
        click.echo(f"Agent {agent_id} stopped")


# ── write-artifact ──────────────────────────────────────────────────


@cli.command("write-artifact")
@click.option("--status", required=True, type=click.Choice(["success", "failure", "escalation"]))
@click.option("--output", required=True, help="JSON output data")
@click.option("--warnings", default="[]", help="JSON array of warning strings")
@click.option("--debt", "debt_json", default="[]", help="JSON array of DebtRecord objects")
@click.option("--json", "json_flag", is_flag=True, help="Output is JSON format")
@click.pass_context
def write_artifact_cmd(ctx, status, output, warnings, debt_json, json_flag):
    """Write a structured artifact (used by worker agents)."""
    from phalanx.artifacts.schema import Artifact
    from phalanx.artifacts.writer import write_artifact

    root = _get_root(ctx)
    db = _get_db(root)

    agent_id = os.environ.get("PHALANX_AGENT_ID", "")
    team_id = os.environ.get("PHALANX_TEAM_ID", "")

    if not agent_id:
        click.echo(
            "Error: PHALANX_AGENT_ID not set — cannot write artifact outside an agent session",
            err=True,
        )
        raise SystemExit(1)
    if not team_id:
        click.echo(
            "Error: PHALANX_TEAM_ID not set — cannot write artifact outside an agent session",
            err=True,
        )
        raise SystemExit(1)

    try:
        output_data = json.loads(output) if json_flag else output
    except json.JSONDecodeError:
        output_data = output

    try:
        warnings_list = json.loads(warnings)
    except json.JSONDecodeError:
        warnings_list = []

    try:
        debt_list = json.loads(debt_json)
    except json.JSONDecodeError:
        debt_list = []

    artifact = Artifact(
        status=status,
        output=output_data,
        warnings=warnings_list,
        debt=debt_list,
        agent_id=agent_id,
        team_id=team_id,
    )

    artifact_dir = root / "teams" / team_id / "agents" / agent_id
    path = write_artifact(artifact_dir, artifact, db=db)

    click.echo(f"Artifact written: {path}")


# ── lock / unlock / lock-status ─────────────────────────────────────


@cli.command("lock")
@click.argument("file_path")
@click.pass_context
def lock_cmd(ctx, file_path):
    """Acquire advisory file lock."""
    from phalanx.comms.file_lock import acquire_lock

    root = _get_root(ctx)
    db = _get_db(root)
    team_id = os.environ.get("PHALANX_TEAM_ID", "unknown")
    agent_id = os.environ.get("PHALANX_AGENT_ID", "unknown")

    success = acquire_lock(db, file_path, team_id, agent_id)
    if ctx.obj.get("json_mode"):
        _json_output({"ok": success, "file": file_path})
    else:
        if success:
            click.echo(f"Lock acquired: {file_path}")
        else:
            click.echo(f"Lock denied: {file_path}", err=True)
            raise SystemExit(1)


@cli.command("unlock")
@click.argument("file_path")
@click.pass_context
def unlock_cmd(ctx, file_path):
    """Release advisory file lock."""
    from phalanx.comms.file_lock import release_lock

    root = _get_root(ctx)
    db = _get_db(root)
    release_lock(db, file_path)
    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "file": file_path})
    else:
        click.echo(f"Lock released: {file_path}")


@cli.command("lock-status")
@click.pass_context
def lock_status_cmd(ctx):
    """Show file locks."""
    root = _get_root(ctx)
    db = _get_db(root)
    team_id = os.environ.get("PHALANX_TEAM_ID")
    locks = db.list_locks(team_id)

    if ctx.obj.get("json_mode"):
        _json_output({"locks": locks})
    else:
        if not locks:
            click.echo("No active locks")
        else:
            for lock in locks:
                click.echo(f"  {lock['file_path']}  (agent={lock['agent_id']}, pid={lock['pid']})")


# ── list-teams / status ─────────────────────────────────────────────


@cli.command("list-teams")
@click.pass_context
def list_teams_cmd(ctx):
    """List all teams with status summary."""
    root = _get_root(ctx)
    db = _get_db(root)
    teams = db.list_teams()

    if ctx.obj.get("json_mode"):
        _json_output({"teams": teams})
    else:
        if not teams:
            click.echo("No teams found")
        else:
            for t in teams:
                agents = db.list_agents(t["id"])
                running = sum(1 for a in agents if a["status"] == "running")
                click.echo(
                    f"  {t['id']}  {t['status']:<10} "
                    f"agents={len(agents)} running={running}  "
                    f"task={t['task'][:60]}"
                )


@cli.command("status")
@click.pass_context
def status_cmd(ctx):
    """Show all running agents and teams."""
    root = _get_root(ctx)
    db = _get_db(root)

    teams = db.list_teams()
    all_agents = db.list_agents()

    result = {
        "teams": len(teams),
        "agents": len(all_agents),
        "running": sum(1 for a in all_agents if a["status"] == "running"),
    }

    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(f"Teams: {result['teams']}")
        click.echo(f"Agents: {result['agents']} ({result['running']} running)")
        for a in all_agents:
            status_icon = {
                "running": "●",
                "pending": "○",
                "dead": "⊘",
                "failed": "✗",
                "blocked_on_prompt": "⏸",
                "suspended": "◑",
            }.get(a["status"], "?")
            click.echo(f"  {status_icon} {a['id']:<30} {a['status']:<20} team={a['team_id']}")


# ── init ─────────────────────────────────────────────────────────────


@cli.command("init")
@click.pass_context
def init_cmd(ctx):
    """Initialize .phalanx/ in the current workspace."""
    from phalanx.init_cmd import init_workspace

    root = _get_root(ctx)
    root.mkdir(parents=True, exist_ok=True)

    # Create soul directory
    soul_dir = root / "soul"
    soul_dir.mkdir(exist_ok=True)

    # Create default config
    config = PhalanxConfig()
    save_config(root, config)

    # Initialize DB
    _get_db(root)

    workspace_dir = root.parent
    result = init_workspace(workspace_dir)

    click.echo(f"Initialized phalanx at {root}")
    click.echo("  Created: config.json, state.db, soul/")
    for skill in result.get("skills_created", []):
        click.echo(f"  Created skill: {skill}")


# ── gc ───────────────────────────────────────────────────────────────


@cli.command("gc")
@click.option("--older-than", default="24h", help="Age threshold (e.g., 24h, 7d)")
@click.option("--all", "gc_all", is_flag=True, help="Delete everything")
@click.pass_context
def gc_cmd(ctx, older_than, gc_all):
    """Run garbage collection on dead teams."""
    from phalanx.monitor.gc import run_gc

    root = _get_root(ctx)
    db = _get_db(root)

    if gc_all:
        hours = 0
    else:
        hours = _parse_duration(older_than)

    deleted = run_gc(root, db=db, max_age_hours=hours)

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "deleted": deleted, "count": len(deleted)})
    else:
        if deleted:
            click.echo(f"Deleted {len(deleted)} teams: {', '.join(deleted)}")
        else:
            click.echo("No teams to clean up")


# ── mcp-server ───────────────────────────────────────────────────────


@cli.command("mcp-server")
@click.option(
    "--workflows-dir",
    envvar="PHALANX_WORKFLOWS_DIR",
    default="./workflows",
    show_default=True,
    help="Directory containing workflow YAML files to expose as MCP tools.",
)
def mcp_server_cmd(workflows_dir: str) -> None:
    """Start the Phalanx MCP server (stdio transport) for Cursor/Claude Desktop."""
    from phalanx.mcp_server import run_mcp_server

    run_mcp_server(workflows_dir=workflows_dir)


def _parse_duration(s: str) -> int:
    """Parse duration string like '24h', '7d', '30m' into hours."""
    s = s.strip().lower()
    if s.endswith("d"):
        return int(s[:-1]) * 24
    elif s.endswith("h"):
        return int(s[:-1])
    elif s.endswith("m"):
        return max(1, int(s[:-1]) // 60)
    else:
        return int(s)


# ── Entry point ──────────────────────────────────────────────────────


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
