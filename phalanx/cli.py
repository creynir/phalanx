"""Phalanx CLI — entry point for multi-agent orchestration.

Subcommands:
  run-agent     Single-agent mode (no team lead needed)
  create-team   Create a team with a team lead
  spawn-agent   Spawn a sub-agent (used by team lead)
  monitor       Blocking DEM-style monitor loop
  team-status   Show team status
  agent-status  Show agent status
  team-result   Read team lead's artifact
  agent-result  Read agent's artifact
  message       Send message to team lead
  message-agent Send message to specific agent
  send-keys     Send raw keystrokes to an agent
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
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
@click.pass_context
def cli(ctx, root, json_mode, verbose):
    """Phalanx — Multi-Agent Orchestration System."""
    ctx.ensure_object(dict)
    ctx.obj["root"] = root
    ctx.obj["json_mode"] = json_mode

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ── run-agent: Single-agent mode ─────────────────────────────────────


@cli.command("run-agent")
@click.argument("task")
@click.option("--backend", "-b", default=None, help="Backend (cursor, claude, gemini, codex)")
@click.option("--model", "-m", default=None, help="Model to use")
@click.option("--auto-approve/--no-auto-approve", default=True, help="Auto-approve tool calls")
@click.pass_context
def run_agent(ctx, task, backend, model, auto_approve):
    """Spawn and manage a single agent (no team lead).

    This is the simplest way to run a single sub-agent, identical in
    capability to a team worker but orchestrated directly by the user
    or Main Agent.
    """
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.lifecycle import run_monitor_loop
    from phalanx.monitor.stall import StallDetector
    from phalanx.process.manager import ProcessManager
    from phalanx.team.spawn import spawn_single_agent

    root = _get_root(ctx)
    config = _get_config(root)
    db = _get_db(root)

    backend_name = backend or config.default_backend
    model_name = model or config.default_model

    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=config.idle_timeout_seconds)
    sd = StallDetector(pm, hb, idle_timeout=config.idle_timeout_seconds)

    team_id, agent_id, agent_proc = spawn_single_agent(
        phalanx_root=root,
        db=db,
        process_manager=pm,
        heartbeat_monitor=hb,
        task=task,
        backend_name=backend_name,
        model=model_name,
        auto_approve=auto_approve,
        config=config,
    )

    result_data = {
        "ok": True,
        "team_id": team_id,
        "agent_id": agent_id,
        "session": agent_proc.session_name,
        "stream_log": str(agent_proc.stream_log),
    }

    if ctx.obj.get("json_mode"):
        _json_output(result_data)
    else:
        click.echo(f"Agent spawned: {agent_id}")
        click.echo(f"  Team:    {team_id}")
        click.echo(f"  Session: {agent_proc.session_name}")
        click.echo(f"  Log:     {agent_proc.stream_log}")
        click.echo(f"  Attach:  tmux attach -t {agent_proc.session_name}")

    # Start monitoring loop
    click.echo("\nMonitoring agent... (Ctrl+C to detach)")
    try:
        mon_result = run_monitor_loop(
            agent_id=agent_id,
            process_manager=pm,
            heartbeat_monitor=hb,
            stall_detector=sd,
            max_retries=config.max_retries,
            max_runtime=config.max_runtime_seconds,
            poll_interval=config.monitor_poll_interval,
        )

        if ctx.obj.get("json_mode"):
            _json_output(mon_result.to_dict())
        else:
            click.echo(f"\nAgent {agent_id} finished: {mon_result.final_state}")
            if mon_result.screen_text:
                click.echo(f"  Screen: {mon_result.screen_text[:200]}")
    except KeyboardInterrupt:
        click.echo(f"\nDetached from agent {agent_id}.")
        click.echo(f"  Re-attach: tmux attach -t {agent_proc.session_name}")
        click.echo(f"  Monitor:   phalanx monitor {agent_id}")


# ── create-team ──────────────────────────────────────────────────────


@cli.command("create-team")
@click.argument("task")
@click.option("--backend", "-b", default=None, help="Backend")
@click.option("--model", "-m", default=None, help="Model")
@click.option("--auto-approve/--no-auto-approve", default=True)
@click.pass_context
def create_team_cmd(ctx, task, backend, model, auto_approve):
    """Create a team and start its team lead."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager
    from phalanx.team.create import create_team

    root = _get_root(ctx)
    config = _get_config(root)
    db = _get_db(root)

    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=config.idle_timeout_seconds)

    team_id, lead_id = create_team(
        phalanx_root=root,
        db=db,
        process_manager=pm,
        heartbeat_monitor=hb,
        task=task,
        backend_name=backend or config.default_backend,
        model=model or config.default_model,
        auto_approve=auto_approve,
        config=config,
    )

    result = {"ok": True, "team_id": team_id, "lead_id": lead_id}
    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(f"Team created: {team_id}")
        click.echo(f"  Lead: {lead_id}")


# ── spawn-agent (used by team lead) ─────────────────────────────────


@cli.command("spawn-agent")
@click.argument("task")
@click.option("--team-id", envvar="PHALANX_TEAM_ID", required=True)
@click.option("--backend", "-b", default=None)
@click.option("--model", "-m", default=None)
@click.option("--worktree", default=None)
@click.option("--auto-approve/--no-auto-approve", default=True)
@click.pass_context
def spawn_agent_cmd(ctx, task, team_id, backend, model, worktree, auto_approve):
    """Spawn a sub-agent in an existing team."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager
    from phalanx.team.spawn import spawn_agent

    root = _get_root(ctx)
    config = _get_config(root)
    db = _get_db(root)

    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=config.idle_timeout_seconds)

    agent_proc = spawn_agent(
        phalanx_root=root,
        db=db,
        process_manager=pm,
        heartbeat_monitor=hb,
        team_id=team_id,
        task=task,
        backend_name=backend or config.default_backend,
        model=model or config.default_model,
        worktree=worktree,
        auto_approve=auto_approve,
        config=config,
    )

    result = {
        "ok": True,
        "agent_id": agent_proc.agent_id,
        "team_id": team_id,
        "session": agent_proc.session_name,
    }
    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(f"Agent spawned: {agent_proc.agent_id}")
        click.echo(f"  Session: {agent_proc.session_name}")


# ── monitor ──────────────────────────────────────────────────────────


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
    sd = StallDetector(pm, hb, idle_timeout=config.idle_timeout_seconds)

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


# ── message / message-agent ─────────────────────────────────────────


@cli.command("message")
@click.argument("team_id")
@click.argument("text")
@click.pass_context
def message_cmd(ctx, team_id, text):
    """Send message to team lead (resumes if dead)."""
    root = _get_root(ctx)
    db = _get_db(root)

    db.send_message(team_id, sender="main", content=text)

    # Find the team lead
    agents = db.list_agents(team_id)
    lead = next((a for a in agents if a["role"] == "lead"), None)
    if lead and lead["status"] == "running":
        from phalanx.comms.messaging import deliver_message
        from phalanx.process.manager import ProcessManager

        pm = ProcessManager(root)
        deliver_message(pm, lead["id"], text)

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "team_id": team_id, "delivered": True})
    else:
        click.echo(f"Message sent to team {team_id}")


@cli.command("message-agent")
@click.argument("agent_id")
@click.argument("text")
@click.option("--team-id", envvar="PHALANX_TEAM_ID", default=None)
@click.pass_context
def message_agent_cmd(ctx, agent_id, text, team_id):
    """Send message to a specific agent."""
    root = _get_root(ctx)
    db = _get_db(root)

    agent = db.get_agent(agent_id)
    if agent is None:
        click.echo(f"Agent '{agent_id}' not found", err=True)
        raise SystemExit(1)

    resolved_team = team_id or agent["team_id"]
    db.send_message(resolved_team, sender="lead", content=text, agent_id=agent_id)

    if agent["status"] == "running":
        from phalanx.comms.messaging import deliver_message
        from phalanx.process.manager import ProcessManager

        pm = ProcessManager(root)
        deliver_message(pm, agent_id, text)

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "agent_id": agent_id, "delivered": True})
    else:
        click.echo(f"Message sent to agent {agent_id}")


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
@click.option(
    "--status", required=True, type=click.Choice(["success", "failure", "escalation_required"])
)
@click.option("--output", required=True, help="JSON output data")
@click.option("--warnings", default="[]", help="JSON array of warning strings")
@click.option("--json", "json_flag", is_flag=True, help="Output is JSON format")
@click.pass_context
def write_artifact_cmd(ctx, status, output, warnings, json_flag):
    """Write a structured artifact (used by worker agents)."""
    from phalanx.artifacts.schema import Artifact
    from phalanx.artifacts.writer import write_artifact

    root = _get_root(ctx)
    db = _get_db(root)

    agent_id = os.environ.get("PHALANX_AGENT_ID", "")
    team_id = os.environ.get("PHALANX_TEAM_ID", "")

    try:
        output_data = json.loads(output) if json_flag else output
    except json.JSONDecodeError:
        output_data = output

    try:
        warnings_list = json.loads(warnings)
    except json.JSONDecodeError:
        warnings_list = []

    artifact = Artifact(
        status=status,
        output=output_data,
        warnings=warnings_list,
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
