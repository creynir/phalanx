"""Phalanx CLI — Click-based entry point with all subcommands."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from phalanx import __version__
from phalanx.config import load_config, set_config_value, get_config_value, ensure_global_config
from phalanx.db import Database
from phalanx.backends import get_backend, detect_default, detect_available

console = Console()


def _get_db() -> Database:
    return Database()


def _get_config(workspace: Path | None = None) -> dict:
    ensure_global_config()
    return load_config(workspace)


def _output(data: dict, as_json: bool = False) -> None:
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        for k, v in data.items():
            click.echo(f"{k}: {v}")


# ── Main Group ─────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.option("--backend", "-b", help="Backend CLI to use (cursor, claude, gemini, codex)")
@click.option("--model", "-m", help="Model to use")
@click.option("--auto-approve", is_flag=True, default=False,
              help="Allow spawning autonomous sub-agents with full permissions")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
@click.option("--version", "-v", is_flag=True, help="Show version")
@click.pass_context
def main(ctx, backend, model, auto_approve, as_json, version):
    """Phalanx — multi-agent orchestration CLI.

    \b
    Start an interactive agent session:
      phalanx                        # uses auto-detected backend
      phalanx -b gemini              # uses gemini backend
      phalanx run "do something"     # with an initial prompt

    \b
    Manage agent teams:
      phalanx --auto-approve create-team --task "..." --agents coder:2,reviewer
      phalanx team-status <team-id> --json
      phalanx stop <team-id>
    """
    ctx.ensure_object(dict)
    ctx.obj["auto_approve"] = auto_approve

    if version:
        click.echo(f"phalanx {__version__}")
        return

    if ctx.invoked_subcommand is None:
        _start_agent(backend=backend, model=model, prompt=None, headless=False)


def _start_agent(backend: str | None, model: str | None, prompt: str | None, headless: bool):
    """Shared logic for starting a single agent session."""
    from phalanx.init_cmd import check_and_prompt_skill

    config = _get_config()
    workspace = Path.cwd()

    if not backend:
        backend = config.get("defaults", {}).get("backend", "") or detect_default()

    b = get_backend(backend)
    if not model:
        model = config.get("defaults", {}).get("model", "") or None

    check_and_prompt_skill(backend, workspace=workspace)

    if headless:
        if not prompt:
            click.echo("Error: --print requires a prompt. Use: phalanx run --print \"prompt\"")
            raise SystemExit(1)
        cmd = b.build_headless_command(prompt, workspace, model=model, auto_approve=True)
    else:
        cmd = b.build_interactive_command(prompt or "", workspace, model=model)

    os.execvp(cmd[0], cmd)


@main.command(name="run")
@click.argument("prompt", required=False, default=None)
@click.option("--backend", "-b", help="Backend CLI")
@click.option("--model", "-m", help="Model to use")
@click.option("--print", "headless", is_flag=True, help="Headless mode — print and exit")
def run_cmd(prompt, backend, model, headless):
    """Start a single agent session, optionally with a prompt."""
    _start_agent(backend=backend, model=model, prompt=prompt, headless=headless)


# ── Init ───────────────────────────────────────────────────

@main.command()
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
@click.option("--json", "as_json", is_flag=True)
def init(workspace, as_json):
    """Detect IDE and create skill files for phalanx integration."""
    from phalanx.init_cmd import init_workspace

    result = init_workspace(Path(workspace))
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        if result["ides_detected"]:
            console.print(f"[green]Detected:[/green] {', '.join(result['ides_detected'])}")
            for s in result["skills_created"]:
                console.print(f"  Created: {s}")
        else:
            console.print("[yellow]No IDEs detected.[/yellow]")


# ── Config ─────────────────────────────────────────────────

@main.group(name="config")
def config_group():
    """Show or modify phalanx configuration."""


@config_group.command(name="show")
@click.option("--json", "as_json", is_flag=True)
def config_show(as_json):
    """Show current configuration."""
    cfg = _get_config()
    if as_json:
        click.echo(json.dumps(cfg, indent=2))
    else:
        _print_config(cfg)


@config_group.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a config value (e.g. defaults.backend cursor)."""
    cfg = set_config_value(key, value)
    console.print(f"[green]Set[/green] {key} = {get_config_value(cfg, key)}")


def _print_config(cfg, prefix=""):
    for k, v in cfg.items():
        if isinstance(v, dict):
            _print_config(v, prefix=f"{prefix}{k}.")
        else:
            click.echo(f"  {prefix}{k} = {v}")


# ── Models ─────────────────────────────────────────────────

@main.group(name="models")
def models_group():
    """Manage model routing configuration."""


@models_group.command(name="show")
@click.option("--json", "as_json", is_flag=True)
def models_show(as_json):
    """Show current model routing table."""
    cfg = _get_config()
    models = cfg.get("models", {})
    if as_json:
        click.echo(json.dumps(models, indent=2))
        return

    table = Table(title="Model Routing")
    table.add_column("Backend")
    roles = ["orchestrator", "coder", "researcher", "reviewer", "architect", "default"]
    for r in roles:
        table.add_column(r)

    for backend_name in ["cursor", "claude", "gemini", "codex"]:
        bm = models.get(backend_name, {})
        row = [backend_name] + [bm.get(r, "-") for r in roles]
        table.add_row(*row)

    console.print(table)


@models_group.command(name="set")
@click.argument("key")
@click.argument("model")
def models_set(key, model):
    """Set model for a backend.role (e.g. cursor.coder opus-4.6)."""
    full_key = f"models.{key}"
    set_config_value(full_key, model)
    console.print(f"[green]Set[/green] {full_key} = {model}")


@models_group.command(name="reset")
def models_reset():
    """Reset model routing to shipped defaults."""
    from phalanx.config import _load_toml, _SHIPPED_CONFIG, save_global_config
    shipped = _load_toml(_SHIPPED_CONFIG)
    cfg = _get_config()
    cfg["models"] = shipped.get("models", {})
    save_global_config(cfg)
    console.print("[green]Model routing reset to defaults.[/green]")


@models_group.command(name="update")
@click.option("--json", "as_json", is_flag=True)
def models_update(as_json):
    """Auto-detect available models and validate config."""
    available = detect_available()
    report = {"available_backends": available, "validated": {}}

    cfg = _get_config()
    for backend_name in available:
        models_cfg = cfg.get("models", {}).get(backend_name, {})
        report["validated"][backend_name] = {
            "roles_configured": list(models_cfg.keys()),
            "status": "ok",
        }

    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        for b in available:
            console.print(f"  [green]✓[/green] {b}: {report['validated'][b]['roles_configured']}")


# ── Status ─────────────────────────────────────────────────

@main.command()
@click.option("--json", "as_json", is_flag=True)
def status(as_json):
    """Show all teams and agents."""
    db = _get_db()
    teams = db.list_teams()

    if as_json:
        click.echo(json.dumps(teams, indent=2, default=str))
        return

    if not teams:
        click.echo("No active teams.")
        return

    table = Table(title="Teams")
    table.add_column("ID")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Backend")
    table.add_column("Created")

    for t in teams:
        table.add_row(t["id"], t["task"][:50], t["status"], t["backend"], t["created_at"])

    console.print(table)
    db.close()


# ── Create Team ────────────────────────────────────────────

@main.command(name="create-team")
@click.option("--task", "-t", required=True, help="Task description for the team")
@click.option("--agents", "-a", default="coder", help="Agent spec: role[:count],... (e.g. researcher,coder:2)")
@click.option("--backend", "-b", help="Backend CLI")
@click.option("--model", "-m", help="Override model for all agents")
@click.option("--worktree", is_flag=True, help="Use git worktrees for isolation")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def create_team_cmd(ctx, task, agents, backend, model, worktree, as_json):
    """Create a team of agents. Requires --auto-approve on phalanx."""
    if not ctx.obj.get("auto_approve"):
        console.print(
            "[red bold]Error:[/red bold] Team creation requires --auto-approve.\n\n"
            "Sub-agents run autonomously in headless sessions and need full\n"
            "permissions to execute tools. Without --auto-approve, they would\n"
            "stall on the first action waiting for human input that cannot\n"
            "be provided.\n\n"
            "[yellow]Restart phalanx with:[/yellow]\n"
            "  phalanx --auto-approve create-team --task \"...\" --agents \"...\"\n\n"
            "Or when using phalanx as a tool from another agent:\n"
            "  phalanx --auto-approve create-team -t \"...\" -a \"...\" --json"
        )
        raise SystemExit(1)

    from phalanx.team.create import create_team

    db = _get_db()
    result = create_team(
        db=db,
        task=task,
        agents_spec=agents,
        backend_name=backend,
        model=model,
        workspace=Path.cwd(),
        use_worktree=worktree,
    )
    db.close()
    _output(result, as_json)


# ── Team Status ────────────────────────────────────────────

@main.command(name="team-status")
@click.argument("team_id")
@click.option("--json", "as_json", is_flag=True)
def team_status_cmd(team_id, as_json):
    """Check status of a team."""
    from phalanx.team.orchestrator import get_team_status

    db = _get_db()
    result = get_team_status(db, team_id)
    db.close()
    _output(result, as_json)


# ── Team Result ────────────────────────────────────────────

@main.command(name="team-result")
@click.argument("team_id")
@click.option("--json", "as_json", is_flag=True)
def team_result_cmd(team_id, as_json):
    """Read the consolidated team result."""
    from phalanx.team.orchestrator import get_team_result

    db = _get_db()
    result = get_team_result(db, team_id)
    db.close()

    if result is None:
        click.echo("No result available yet.")
        return
    _output(result, as_json)


# ── Message ────────────────────────────────────────────────

@main.command()
@click.argument("team_id")
@click.argument("msg")
@click.option("--json", "as_json", is_flag=True)
def message(team_id, msg, as_json):
    """Send a message to the team lead."""
    from phalanx.comms.messaging import deliver_message

    db = _get_db()
    agents = db.list_agents(team_id=team_id)
    lead = next((a for a in agents if a["role"] == "lead"), None)

    if lead is None or not lead.get("tmux_session"):
        _output({"error": "No active team lead found"}, as_json)
        db.close()
        return

    success = deliver_message(lead["tmux_session"], msg)
    if success:
        db.insert_message(team_id, "user", msg, agent_id=lead["id"], delivered=True)

    _output({"delivered": success, "team_id": team_id}, as_json)
    db.close()


# ── Stop ───────────────────────────────────────────────────

@main.command()
@click.argument("team_id")
@click.option("--json", "as_json", is_flag=True)
def stop(team_id, as_json):
    """Stop a team (data preserved for resume)."""
    from phalanx.team.orchestrator import stop_team

    db = _get_db()
    result = stop_team(db, team_id)
    db.close()
    _output(result, as_json)


# ── Resume ─────────────────────────────────────────────────

@main.command()
@click.argument("team_id")
@click.option("--json", "as_json", is_flag=True)
def resume(team_id, as_json):
    """Resume a stopped team."""
    db = _get_db()
    team = db.get_team(team_id)

    if team is None:
        _output({"error": f"Team {team_id} not found"}, as_json)
        db.close()
        return

    agents = db.list_agents(team_id=team_id)
    resumed = 0

    for agent in agents:
        if agent["status"] == "dead" and agent.get("chat_id"):
            backend = get_backend(agent["backend"])
            cmd = backend.build_resume_command(agent["chat_id"])
            from phalanx.process.manager import spawn_in_tmux
            from phalanx.artifacts.writer import get_stream_log_path

            stream_log = get_stream_log_path(team_id, agent["id"])
            result = spawn_in_tmux(
                cmd=cmd, team_id=team_id, agent_id=agent["id"],
                stream_log=stream_log, working_dir=Path.cwd(),
            )
            db.update_agent(agent["id"], status="running",
                            tmux_session=result["session_name"],
                            pid=result["pane_pid"])
            resumed += 1

    if resumed > 0:
        db.update_team(team_id, status="running")

    _output({"team_id": team_id, "resumed": resumed}, as_json)
    db.close()


# ── Agent Tools (called by agents via shell) ───────────────

@main.command(name="write-artifact")
@click.option("--status", "art_status", required=True,
              type=click.Choice(["success", "failure", "escalation_required"]))
@click.option("--output", "art_output", required=True, help="JSON output string")
@click.option("--json", "as_json", is_flag=True)
def write_artifact_cmd(art_status, art_output, as_json):
    """Write an artifact (used by agents)."""
    from phalanx.artifacts.writer import write_artifact

    try:
        output_data = json.loads(art_output)
    except json.JSONDecodeError:
        output_data = {"raw": art_output}

    artifact = write_artifact(art_status, output_data)

    # Update DB
    db = _get_db()
    db.update_agent(artifact.agent_id, artifact_status=art_status)
    db.close()

    result = artifact.model_dump()
    result["warning"] = "Artifacts are ephemeral — deleted after 24h of team inactivity."
    _output(result, as_json)


@main.command(name="agent-status")
@click.argument("agent_id", required=False)
@click.option("--json", "as_json", is_flag=True)
def agent_status_cmd(agent_id, as_json):
    """Check agent status."""
    db = _get_db()

    if agent_id:
        agent = db.get_agent(agent_id)
        if agent is None:
            _output({"error": "Agent not found"}, as_json)
        else:
            from phalanx.monitor.lifecycle import check_agent_health
            check_agent_health(db, agent_id)
            _output(db.get_agent(agent_id), as_json)
    else:
        team_id = os.environ.get("PHALANX_TEAM_ID", "")
        if team_id:
            agents = db.list_agents(team_id=team_id)
            if as_json:
                click.echo(json.dumps(agents, indent=2, default=str))
            else:
                for a in agents:
                    click.echo(f"  {a['id']}: {a['status']} ({a['role']})")
        else:
            _output({"error": "Provide agent_id or set PHALANX_TEAM_ID"}, as_json)

    db.close()


@main.command(name="agent-result")
@click.argument("agent_id")
@click.option("--json", "as_json", is_flag=True)
def agent_result_cmd(agent_id, as_json):
    """Read an agent's artifact."""
    db = _get_db()
    agent = db.get_agent(agent_id)
    db.close()

    if agent is None:
        _output({"error": "Agent not found"}, as_json)
        return

    from phalanx.artifacts.reader import read_artifact
    artifact = read_artifact(agent["team_id"], agent_id)

    if artifact is None:
        _output({"error": "No artifact yet"}, as_json)
    else:
        _output(artifact.model_dump(), as_json)


@main.command(name="message-agent")
@click.argument("agent_id")
@click.argument("msg")
@click.option("--json", "as_json", is_flag=True)
def message_agent_cmd(agent_id, msg, as_json):
    """Send a message to a specific agent."""
    from phalanx.comms.messaging import deliver_message

    db = _get_db()
    agent = db.get_agent(agent_id)

    if agent is None or not agent.get("tmux_session"):
        _output({"error": "Agent not found or not running"}, as_json)
        db.close()
        return

    success = deliver_message(agent["tmux_session"], msg)
    if success:
        db.insert_message(agent["team_id"], "lead", msg,
                          agent_id=agent_id, delivered=True)

    _output({"delivered": success, "agent_id": agent_id}, as_json)
    db.close()


@main.command(name="lock")
@click.argument("file_path")
@click.option("--json", "as_json", is_flag=True)
def lock_cmd(file_path, as_json):
    """Acquire a file lock."""
    from phalanx.comms.file_lock import acquire_lock

    team_id = os.environ.get("PHALANX_TEAM_ID", "")
    agent_id = os.environ.get("PHALANX_AGENT_ID", "")

    if not team_id or not agent_id:
        _output({"error": "PHALANX_TEAM_ID and PHALANX_AGENT_ID must be set"}, as_json)
        return

    db = _get_db()
    acquired = acquire_lock(db, file_path, team_id, agent_id)
    _output({"file": file_path, "acquired": acquired}, as_json)
    db.close()


@main.command(name="unlock")
@click.argument("file_path")
@click.option("--json", "as_json", is_flag=True)
def unlock_cmd(file_path, as_json):
    """Release a file lock."""
    from phalanx.comms.file_lock import release_lock

    db = _get_db()
    release_lock(db, file_path)
    _output({"file": file_path, "released": True}, as_json)
    db.close()


@main.command(name="lock-status")
@click.option("--json", "as_json", is_flag=True)
def lock_status_cmd(as_json):
    """Show active file locks."""
    team_id = os.environ.get("PHALANX_TEAM_ID", "")
    if not team_id:
        _output({"error": "PHALANX_TEAM_ID must be set"}, as_json)
        return

    db = _get_db()
    locks = db.list_locks(team_id)
    db.close()

    if as_json:
        click.echo(json.dumps(locks, indent=2, default=str))
    else:
        if not locks:
            click.echo("No active locks.")
        for lock in locks:
            click.echo(f"  {lock['file_path']} locked by {lock['agent_id']}")


if __name__ == "__main__":
    main()
