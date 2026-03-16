"""phalanx msg * — messaging commands."""
from __future__ import annotations

import json

import click


def _get_root(ctx: click.Context):
    from pathlib import Path
    return Path(ctx.obj.get("root", ".phalanx")).resolve()


def _get_db(root):
    from phalanx.db import StateDB
    return StateDB(root / "state.db")


def _json_output(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@click.group("msg")
def msg_group():
    """Send messages to team leads or specific agents."""


@msg_group.command("lead")
@click.argument("team_id")
@click.argument("text")
@click.pass_context
def msg_lead_cmd(ctx, team_id, text):
    """Send a message to the team lead for TEAM_ID."""
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
            f"Use 'phalanx team resume {team_id}' to restart it.",
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


@msg_group.command("agent")
@click.argument("agent_id")
@click.argument("text")
@click.pass_context
def msg_agent_cmd(ctx, agent_id, text):
    """Send a message to a specific agent AGENT_ID."""
    from phalanx.comms.messaging import deliver_message
    from phalanx.process.manager import ProcessManager

    root = _get_root(ctx)
    db = _get_db(root)

    agent = db.get_agent(agent_id)
    if agent is None:
        click.echo(f"Agent '{agent_id}' not found", err=True)
        raise SystemExit(1)

    status = agent["status"]
    if status not in ("running", "blocked_on_prompt"):
        click.echo(
            f"Error: Agent {agent_id} is {status} — message not delivered.\n"
            f"Use 'phalanx agent resume {agent_id}' to restart it.",
            err=True,
        )
        if ctx.obj.get("json_mode"):
            _json_output({"ok": False, "agent_id": agent_id, "delivered": False, "status": status})
        raise SystemExit(1)

    pm = ProcessManager(root)
    delivered = deliver_message(pm, agent_id, text)

    if status == "blocked_on_prompt" and delivered:
        db.update_agent(agent_id, status="running")

    if ctx.obj.get("json_mode"):
        _json_output({"ok": delivered, "agent_id": agent_id, "delivered": delivered})
    else:
        click.echo(f"Message delivered to agent {agent_id}")
