"""phalanx team * — team management commands."""
from __future__ import annotations

import json
from pathlib import Path

import click

_EXAMPLE_CONFIG = {
    "lead": {
        "model": "opus-4.6",
        "prompt": "You are the team lead. Delegate tasks to agents and synthesize results.",
        "backend": "cursor",
    },
    "agents": [
        {
            "model": "sonnet-4.6",
            "prompt": "Implement the feature described by the lead.",
            "backend": "cursor",
        }
    ],
    "idle_timeout": 1800,
    "max_runtime": 3600,
}

def _get_root(ctx: click.Context) -> Path:
    return Path(ctx.obj.get("root", ".phalanx")).resolve()

def _get_db(root: Path):
    from phalanx.db import StateDB
    return StateDB(root / "state.db")

def _get_config(root: Path):
    from phalanx.config import load_config
    return load_config(root)

def _json_output(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))

def _parse_duration(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("d"):
        return int(s[:-1]) * 24
    if s.endswith("h"):
        return int(s[:-1])
    if s.endswith("m"):
        return max(1, int(s[:-1]) // 60)
    return int(s)

@click.group("team")
def team_group():
    """Manage agent teams."""
@team_group.command("create")
@click.option("--task", default=None, help="Shared task for the team")
@click.option("--config", "config_path", default=None, type=click.Path(exists=True), help="JSON config file")
@click.option("--agents", "-a", default="coder", help="Agent spec: role[:count],...")
@click.option("--backend", "-b", default=None, help="Backend")
@click.option("--model", "-m", default=None, help="Model")
@click.option("--idle-timeout", type=int, default=None, help="Idle timeout in seconds")
@click.option("--max-runtime", type=int, default=None, help="Max runtime in seconds")
@click.option("--worktree", is_flag=True, help="Create a git worktree for the team")
@click.option("--auto-approve", is_flag=True, help="Enable auto-approve for spawned agents")
@click.option("--example", is_flag=True, help="Print a v2 config example and exit")
@click.pass_context
def team_create_cmd(ctx, task, config_path, agents, backend, model, idle_timeout, max_runtime, worktree, auto_approve, example):
    """Create a new agent team. Use --config for per-agent prompts or --task for a shared task."""
    if example:
        click.echo(json.dumps(_EXAMPLE_CONFIG, indent=2))
        return
    from phalanx.init_cmd import check_and_prompt_skill
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager
    from phalanx.team.config import resolve_backend_for_role
    root = _get_root(ctx)
    cfg = _get_config(root)
    db = _get_db(root)
    backend_name = backend or cfg.default_backend
    auto_approve = auto_approve or ctx.obj.get("auto_approve", False)
    eff_idle = idle_timeout or cfg.idle_timeout
    eff_max = max_runtime or cfg.max_runtime
    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=eff_idle)
    if config_path:
        from phalanx.team.config import load_team_config_v2, v2_to_v1_team_config, validate_team_models
        from phalanx.team.create import create_team_from_config
        tc_v2 = load_team_config_v2(Path(config_path))
        tc = v2_to_v1_team_config(tc_v2, task=task or "")
        validate_team_models(tc, backend_name, backend_overrides=cfg.backend_overrides)
        bes = {s.backend or resolve_backend_for_role(s.role, backend_name, cfg.backend_overrides) for s in tc.agents}
        bes.add(tc.lead.backend or resolve_backend_for_role("lead", backend_name, cfg.backend_overrides))
        for b in sorted(bes):
            check_and_prompt_skill(b, workspace=Path.cwd())
        tid, lid, wids = create_team_from_config(phalanx_root=root, db=db, process_manager=pm,
            heartbeat_monitor=hb, team_config=tc, backend_name=backend_name, auto_approve=auto_approve,
            config=cfg, idle_timeout=eff_idle, max_runtime=eff_max, worktree=worktree)
        result = {"ok": True, "team_id": tid, "lead_id": lid, "worker_ids": wids}
    else:
        if not task:
            click.echo("Error: --task required when --config is not provided", err=True)
            raise SystemExit(1)
        from phalanx.team.create import create_team, parse_agents_spec
        bes = {resolve_backend_for_role("lead", backend_name, cfg.backend_overrides)}
        for role, _ in parse_agents_spec(agents):
            bes.add(resolve_backend_for_role(role, backend_name, cfg.backend_overrides))
        for b in sorted(bes):
            check_and_prompt_skill(b, workspace=Path.cwd())
        tid, lid = create_team(phalanx_root=root, db=db, process_manager=pm, heartbeat_monitor=hb,
            task=task, agents_spec=agents, backend_name=backend_name, model=model or cfg.default_model,
            auto_approve=auto_approve, config=cfg, idle_timeout=eff_idle, max_runtime=eff_max, worktree=worktree)
        result = {"ok": True, "team_id": tid, "lead_id": lid}
    if ctx.obj.get("json_mode"):
        _json_output(result)
    else:
        click.echo(f"Team created: {result['team_id']}")
        click.echo(f"  Lead: {result['lead_id']}")
        for wid in result.get("worker_ids", []):
            click.echo(f"  Worker: {wid}")
@team_group.command("list")
@click.pass_context
def team_list_cmd(ctx):
    """List all teams with status summary."""
    root = _get_root(ctx)
    db = _get_db(root)
    teams = db.list_teams()
    if ctx.obj.get("json_mode"):
        _json_output({"teams": teams})
    elif not teams:
        click.echo("No teams found")
    else:
        for t in teams:
            ag = db.list_agents(t["id"])
            running = sum(1 for a in ag if a["status"] == "running")
            click.echo(f"  {t['id']}  {t['status']:<10} agents={len(ag)} running={running}  task={t['task'][:60]}")
@team_group.command("status")
@click.argument("team_id", required=False, default=None)
@click.pass_context
def team_status_cmd(ctx, team_id):
    """Show team status. Without TEAM_ID, shows all teams."""
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
@team_group.command("result")
@click.argument("team_id")
@click.pass_context
def team_result_cmd(ctx, team_id):
    """Read the team lead's artifact for TEAM_ID."""
    from phalanx.team.orchestrator import get_team_result
    root = _get_root(ctx)
    result = get_team_result(root, team_id)
    if result is None:
        click.echo(f"No artifact found for team '{team_id}'", err=True)
        raise SystemExit(1)
    _json_output(result)
@team_group.command("stop")
@click.argument("team_id")
@click.pass_context
def team_stop_cmd(ctx, team_id):
    """Stop TEAM_ID (kill processes, keep data, resumable)."""
    from phalanx.process.manager import ProcessManager
    from phalanx.team.orchestrator import stop_team
    root = _get_root(ctx)
    result = stop_team(_get_db(root), ProcessManager(root), team_id)
    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, **result})
    else:
        click.echo(f"Team {team_id} stopped ({len(result['stopped_agents'])} agents killed)")
@team_group.command("resume")
@click.argument("team_id")
@click.option("--lead-only", is_flag=True, default=False, help="Resume only the team lead")
@click.option("--auto-approve", is_flag=True, help="Enable auto-approve when resuming")
@click.pass_context
def team_resume_cmd(ctx, team_id, lead_only, auto_approve):
    """Resume a stopped/dead team TEAM_ID."""
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.process.manager import ProcessManager
    from phalanx.team.orchestrator import resume_team
    root = _get_root(ctx)
    cfg = _get_config(root)
    db = _get_db(root)
    if db.get_team(team_id) is None:
        click.echo(f"Error: Team '{team_id}' not found", err=True)
        raise SystemExit(1)
    result = resume_team(phalanx_root=root, db=db, process_manager=ProcessManager(root),
        heartbeat_monitor=HeartbeatMonitor(idle_timeout=cfg.idle_timeout),
        team_id=team_id, resume_all=not lead_only,
        auto_approve=auto_approve or ctx.obj.get("auto_approve", False))
    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, **result})
    else:
        click.echo(f"Team {team_id} resumed")
        for aid in result.get("resumed_agents", []):
            click.echo(f"  Resumed: {aid}")
@team_group.command("broadcast")
@click.argument("team_id")
@click.argument("text")
@click.pass_context
def team_broadcast_cmd(ctx, team_id, text):
    """Broadcast TEXT to all agents in TEAM_ID."""
    from phalanx.comms.messaging import broadcast_message
    from phalanx.process.manager import ProcessManager
    root = _get_root(ctx)
    db = _get_db(root)
    agents = {a["id"]: a for a in db.list_agents(team_id)}
    results = broadcast_message(ProcessManager(root), db, team_id, text)
    delivered = sum(1 for v in results.values() if v)
    skipped = {aid: agents[aid]["status"] for aid, ok in results.items() if not ok and aid in agents}
    if ctx.obj.get("json_mode"):
        _json_output({"ok": delivered > 0, "team_id": team_id, "delivered": delivered,
            "total": len(results), "results": results, "skipped": skipped})
    else:
        click.echo(f"Broadcast to team {team_id}: {delivered}/{len(results)} delivered")
        if skipped:
            click.echo(f"  Skipped: {', '.join(f'{a} ({s})' for a, s in skipped.items())}")
@team_group.command("monitor")
@click.argument("team_id")
@click.option("--idle-timeout", type=int, default=None)
@click.option("--max-runtime", type=int, default=None)
@click.pass_context
def team_monitor_cmd(ctx, team_id, idle_timeout, max_runtime):
    """Per-team monitoring daemon for TEAM_ID. Auto-spawned by team create."""
    from phalanx.costs.aggregator import CostAggregator
    from phalanx.monitor.heartbeat import HeartbeatMonitor
    from phalanx.monitor.stall import StallDetector
    from phalanx.monitor.team_monitor import run_team_monitor
    from phalanx.process.manager import ProcessManager
    root = _get_root(ctx)
    config = _get_config(root)
    db = _get_db(root)
    eff_idle = idle_timeout or config.idle_timeout
    eff_max = max_runtime or config.max_runtime
    if db.get_team(team_id) is None:
        click.echo(f"Error: Team '{team_id}' not found", err=True)
        raise SystemExit(1)
    pm = ProcessManager(root)
    hb = HeartbeatMonitor(idle_timeout=eff_idle)
    for agent in db.list_agents(team_id):
        sl = root / "teams" / team_id / "agents" / agent["id"] / "stream.log"
        if sl.exists() or sl.parent.exists():
            hb.register(agent["id"], sl)
        pm.discover_agent(team_id, agent["id"])
    leads = [a for a in db.list_agents(team_id) if a.get("role") == "lead"]
    click.echo(f"Team monitor started for {team_id} (idle={eff_idle}s, max_runtime={eff_max}s)")
    run_team_monitor(team_id=team_id, db=db, process_manager=pm, heartbeat_monitor=hb,
        stall_detector=StallDetector(pm, hb, idle_timeout=eff_idle, db=db),
        poll_interval=config.monitor_poll_interval, idle_timeout=eff_idle,
        lead_agent_id=leads[0]["id"] if leads else None,
        message_dir=root / "teams" / team_id / "messages", phalanx_root=root,
        cost_aggregator=CostAggregator(db))
@team_group.command("gc")
@click.option("--older-than", default="24h", help="Age threshold (e.g., 24h, 7d)")
@click.option("--all", "gc_all", is_flag=True, help="Delete everything")
@click.pass_context
def team_gc_cmd(ctx, older_than, gc_all):
    """Run garbage collection on dead teams."""
    from phalanx.monitor.gc import run_gc
    root = _get_root(ctx)
    deleted = run_gc(root, db=_get_db(root), max_age_hours=0 if gc_all else _parse_duration(older_than))
    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "deleted": deleted, "count": len(deleted)})
    elif deleted:
        click.echo(f"Deleted {len(deleted)} teams: {', '.join(deleted)}")
    else:
        click.echo("No teams to clean up")
