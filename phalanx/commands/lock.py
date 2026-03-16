"""phalanx lock * — advisory file lock commands."""
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


@click.group("lock")
def lock_group():
    """Manage advisory file locks."""


@lock_group.command("acquire")
@click.argument("file_path")
@click.pass_context
def lock_acquire_cmd(ctx, file_path):
    """Acquire an advisory file lock on FILE_PATH."""
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


@lock_group.command("release")
@click.argument("file_path")
@click.pass_context
def lock_release_cmd(ctx, file_path):
    """Release an advisory file lock on FILE_PATH."""
    from phalanx.comms.file_lock import release_lock

    root = _get_root(ctx)
    db = _get_db(root)
    release_lock(db, file_path)
    if ctx.obj.get("json_mode"):
        _json_output({"ok": True, "file": file_path})
    else:
        click.echo(f"Lock released: {file_path}")


@lock_group.command("status")
@click.pass_context
def lock_status_cmd(ctx):
    """Show all active file locks."""
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
                click.echo(
                    f"  {lock['file_path']}  (agent={lock['agent_id']}, pid={lock['pid']})"
                )
