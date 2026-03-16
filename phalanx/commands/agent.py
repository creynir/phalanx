"""phalanx agent * — agent management commands."""
from __future__ import annotations

import json
import os

import click


def _get_root(ctx: click.Context):
    from pathlib import Path
    return Path(ctx.obj.get("root", ".phalanx")).resolve()


def _get_db(root):
    from phalanx.db import StateDB
    return StateDB(root / "state.db")


def _get_config(root):
    from phalanx.config import load_config
    return load_config(root)


def _json_output(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@click.group("agent")
def agent_group():
    """Manage individual agents."""


@agent_group.command("status")
@click.argument("agent_id", required=False, default=None)
@click.pass_context
def agent_status_cmd(ctx, agent_id):
    """Show agent status. Without AGENT_ID, list all agents."""
    root = _get_root(ctx)
    db = _get_db(root)
    if agent_id:
        result = db.get_agent(agent_id)
        if result is None:
            click.echo(f"Agent '{agent_id}' not found", err=True)
            raise SystemExit(1)
    else:
        result = {"agents": db.list_agents()}
    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(json.dumps(result, indent=2, default=str))


@agent_group.command("result")
@click.argument("agent_id")
@click.pass_context
def agent_result_cmd(ctx, agent_id):
    """Read the artifact for AGENT_ID. Looks up team from DB."""
    from phalanx.team.orchestrator import get_agent_result
    root = _get_root(ctx)
    db = _get_db(root)
    team_id = db.find_team_for_agent(agent_id)
    if team_id is None:
        click.echo(f"Error: Agent '{agent_id}' not found in DB", err=True)
        raise SystemExit(1)
    result = get_agent_result(root, team_id, agent_id)
    if result is None:
        click.echo(f"No artifact found for agent '{agent_id}'", err=True)
        raise SystemExit(1)
    _json_output(result)


@agent_group.command("stop")
@click.argument("agent_id")
@click.pass_context
def agent_stop_cmd(ctx, agent_id):
    """Stop a specific agent AGENT_ID."""
    from phalanx.process.manager import ProcessManager
    root = _get_root(ctx)
    db = _get_db(root)
    ProcessManager(root).kill_agent(agent_id)
    db.update_agent(agent_id, status="dead")
    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "agent_id": agent_id, "status": "dead"})
    else:
        click.echo(f"Agent {agent_id} stopped")


@agent_group.command("resume")
@click.argument("agent_id")
@click.option("--reply", default=None, help="Reply keystrokes for agents blocked on a prompt")
@click.option("--auto-approve", is_flag=True, help="Enable auto-approve for resumed agent")
@click.pass_context
def agent_resume_cmd(ctx, agent_id, reply, auto_approve):
    """Resume a stopped/blocked agent AGENT_ID."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager
    from phalanx.team.orchestrator import resume_single_agent
    root = _get_root(ctx)
    cfg = _get_config(root)
    db = _get_db(root)
    pm = ProcessManager(root)
    agent = db.get_agent(agent_id)
    if agent is None:
        if ctx.obj.get("json_mode"):
            _json_output({"ok": False, "error": f"Agent {agent_id} not found"})
        else:
            click.echo(f"Error: Agent {agent_id} not found", err=True)
        raise SystemExit(1)
    if agent["status"] == "blocked_on_prompt":
        if reply is None:
            click.echo(f"Error: Agent {agent_id} is blocked_on_prompt.\nUse --reply to send a response.", err=True)
            if ctx.obj.get("json_mode"):
                _json_output({"ok": False, "agent_id": agent_id, "status": "blocked_on_prompt", "hint": "Use --reply <text> to unblock"})
            raise SystemExit(1)
        success = pm.send_keys(agent_id, reply, enter=True)
        if success:
            db.update_agent(agent_id, status="running")
        result = {"agent_id": agent_id, "team_id": agent["team_id"],
            "status": "running" if success else "blocked_on_prompt", "unblocked": success}
        if ctx.obj.get("json_mode"):
            _json_output({"ok": success, **result})
        elif success:
            click.echo(f"Agent {agent_id} unblocked (replied: {reply!r})")
        else:
            click.echo(f"Failed to send reply to agent {agent_id}", err=True)
            raise SystemExit(1)
        return
    try:
        result = resume_single_agent(phalanx_root=root, db=db, process_manager=pm,
            heartbeat_monitor=HeartbeatMonitor(idle_timeout=cfg.idle_timeout),
            agent_id=agent_id, auto_approve=auto_approve or ctx.obj.get("auto_approve", False))
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


@agent_group.command("monitor")
@click.argument("agent_id")
@click.pass_context
def agent_monitor_cmd(ctx, agent_id):
    """Blocking monitor loop for AGENT_ID."""
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
    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=config.idle_timeout)
    hb.register(agent_id, root / "teams" / agent["team_id"] / "agents" / agent_id / "stream.log")
    sd = StallDetector(pm, hb, idle_timeout=config.idle_timeout, db=db)
    result = run_monitor_loop(agent_id=agent_id, process_manager=pm, heartbeat_monitor=hb,
        stall_detector=sd, max_retries=config.max_retries, max_runtime=config.max_runtime,
        poll_interval=config.monitor_poll_interval)
    if ctx.obj.get("json_mode"):
        _json_output(result.to_dict())
    else:
        click.echo(json.dumps(result.to_dict(), indent=2))


@agent_group.command("keys")
@click.argument("agent_id")
@click.argument("keys")
@click.option("--no-enter", is_flag=True, help="Don't press Enter after keys")
@click.pass_context
def agent_keys_cmd(ctx, agent_id, keys, no_enter):
    """Send raw keystrokes KEYS to AGENT_ID's tmux pane."""
    from phalanx.process.manager import ProcessManager
    root = _get_root(ctx)
    success = ProcessManager(root).send_keys(agent_id, keys, enter=not no_enter)
    if ctx.obj.get("json_mode"):
        _json_output({"ok": success, "agent_id": agent_id, "keys": keys})
    elif success:
        click.echo(f"Keys sent to {agent_id}: {keys!r}")
    else:
        click.echo(f"Failed to send keys to {agent_id}", err=True)
        raise SystemExit(1)


@agent_group.command("done")
@click.option("--output", required=True, help="JSON output data (required)")
@click.option("--failed", "is_failed", is_flag=True, help="Mark as failure")
@click.option("--escalate", "is_escalate", is_flag=True, help="Mark as escalation")
@click.option("--status", type=click.Choice(["success", "failure", "escalation"]), default=None,
    help="Status alias for scripts (overrides --failed/--escalate)")
@click.option("--warnings", default="[]")
@click.option("--debt", "debt_json", default="[]")
@click.pass_context
def agent_done_cmd(ctx, output, is_failed, is_escalate, status, warnings, debt_json):
    """Write agent artifact and mark task complete. Success by default; use --failed or --escalate."""
    from phalanx.artifacts.schema import Artifact
    from phalanx.artifacts.writer import write_artifact
    root = _get_root(ctx)
    db = _get_db(root)
    agent_id = os.environ.get("PHALANX_AGENT_ID", "")
    team_id = os.environ.get("PHALANX_TEAM_ID", "")
    if not agent_id:
        click.echo("Error: PHALANX_AGENT_ID not set", err=True)
        raise SystemExit(1)
    if not team_id:
        click.echo("Error: PHALANX_TEAM_ID not set", err=True)
        raise SystemExit(1)
    resolved = status or ("escalation" if is_escalate else "failure" if is_failed else "success")
    try:
        output_data = json.loads(output)
    except json.JSONDecodeError:
        output_data = output
    warnings_list = json.loads(warnings) if warnings else []
    debt_list = json.loads(debt_json) if debt_json else []
    artifact = Artifact(status=resolved, output=output_data, warnings=warnings_list,
        debt=debt_list, agent_id=agent_id, team_id=team_id)
    path = write_artifact(root / "teams" / team_id / "agents" / agent_id, artifact, db=db)
    click.echo(f"Artifact written: {path}")


@agent_group.command("logs")
@click.argument("agent_id")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of lines to show (default 50)")
@click.pass_context
def agent_logs_cmd(ctx, agent_id, follow, lines):
    """Tail the stream log for AGENT_ID."""
    import time
    root = _get_root(ctx)
    db = _get_db(root)
    agent = db.get_agent(agent_id)
    if agent is None:
        click.echo(f"Error: Agent '{agent_id}' not found", err=True)
        raise SystemExit(1)
    stream_log = root / "teams" / agent["team_id"] / "agents" / agent_id / "stream.log"
    if not stream_log.exists():
        click.echo(f"Error: No stream log found at {stream_log}", err=True)
        raise SystemExit(1)
    with open(stream_log, "r", errors="replace") as f:
        for line in f.readlines()[-lines:]:
            click.echo(line, nl=False)
    if follow:
        with open(stream_log, "r", errors="replace") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    click.echo(line, nl=False)
                else:
                    time.sleep(0.1)


@agent_group.command("models")
@click.option("--backend", required=True, help="Backend name (cursor, claude, gemini, codex)")
def agent_models_cmd(backend):
    """List available models for the given backend."""
    from phalanx.backends.registry import get_backend
    try:
        models = get_backend(backend).list_models()
    except Exception as e:
        click.echo(f"Error: Unknown backend '{backend}': {e}", err=True)
        raise SystemExit(1)
    if not models:
        click.echo(f"No models listed for backend '{backend}'")
    else:
        for m in models:
            click.echo(m)
