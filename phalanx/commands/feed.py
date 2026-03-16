"""phalanx feed * — team feed read/post commands."""
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


def _json_output(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@click.group("feed")
def feed_group():
    """Read and post to the team feed."""


@feed_group.command("read")
@click.argument("team_id", required=False, default=None, envvar="PHALANX_TEAM_ID")
@click.option("--limit", default=50, help="Max messages to show")
@click.option("--since", default=None, help="Minutes ago (e.g., 5)")
@click.pass_context
def feed_read_cmd(ctx, team_id, limit, since):
    """Read the team feed. TEAM_ID defaults to PHALANX_TEAM_ID env var."""
    import time as _time

    if not team_id:
        click.echo("Error: TEAM_ID required (or set PHALANX_TEAM_ID)", err=True)
        raise SystemExit(1)

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


@feed_group.command("post")
@click.argument("text")
@click.pass_context
def feed_post_cmd(ctx, text):
    """Post a message to the team feed."""
    team_id = os.environ.get("PHALANX_TEAM_ID", "")
    if not team_id:
        click.echo("Error: PHALANX_TEAM_ID not set", err=True)
        raise SystemExit(1)

    root = _get_root(ctx)
    db = _get_db(root)

    sender_id = os.environ.get("PHALANX_AGENT_ID", "external")
    msg_id = db.post_to_feed(team_id, sender_id, text)

    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "message_id": msg_id, "team_id": team_id})
    else:
        click.echo(f"Posted to team {team_id} feed")
