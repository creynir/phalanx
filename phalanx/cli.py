"""Phalanx CLI — thin entry point for multi-agent orchestration.

Subcommand groups:
  team      Manage agent teams (create, list, status, result, costs, ...)
  agent     Manage individual agents (status, result, done, logs, models, ...)
  msg       Send messages (msg lead, msg agent)
  feed      Team feed (feed read, feed post)
  lock      File locks (lock acquire, lock release, lock status)

Flat commands:
  init      Initialize .phalanx/ in workspace

Run without a subcommand to launch your agent with phalanx skills.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import click

from phalanx import __version__
from phalanx.commands import agent_group, feed_group, lock_group, msg_group, team_group

logger = logging.getLogger(__name__)

PHALANX_ROOT_DEFAULT = ".phalanx"


def _get_root(ctx: click.Context) -> Path:
    return Path(ctx.obj.get("root", PHALANX_ROOT_DEFAULT)).resolve()


def _get_config(root: Path):
    from phalanx.config import load_config
    return load_config(root)


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

      phalanx --auto-approve --model gpt-5.4
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
    """Launch the backend agent CLI with phalanx skills installed."""
    from phalanx.backends.registry import detect_backend, get_backend
    from phalanx.init_cmd import check_and_prompt_skill, init_workspace

    root = _get_root(ctx)

    if not root.exists():
        workspace = root.parent if root.name == ".phalanx" else Path.cwd()
        click.echo("Initializing phalanx...")
        init_workspace(workspace)
        root.mkdir(parents=True, exist_ok=True)

    config = _get_config(root)
    backend_name = backend or config.default_backend

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

    check_and_prompt_skill(backend_name, workspace=Path.cwd())

    binary = be.binary_name()
    cmd = [binary]

    if auto_approve:
        cmd.extend(be.auto_approve_flags())

    if model or config.default_model:
        cmd.extend(["--model", model or config.default_model])

    click.echo(f"Launching {backend_name} agent...")
    os.execvp(binary, cmd)


# ── init ─────────────────────────────────────────────────────────────


@cli.command("init")
@click.pass_context
def init_cmd(ctx):
    """Initialize .phalanx/ in the current workspace."""
    from phalanx.config import PhalanxConfig, save_config
    from phalanx.db import StateDB
    from phalanx.init_cmd import init_workspace

    root = _get_root(ctx)
    root.mkdir(parents=True, exist_ok=True)

    soul_dir = root / "soul"
    soul_dir.mkdir(exist_ok=True)

    config = PhalanxConfig()
    save_config(root, config)

    StateDB(root / "state.db")

    workspace_dir = root.parent
    result = init_workspace(workspace_dir)

    click.echo(f"Initialized phalanx at {root}")
    click.echo("  Created: config.json, state.db, soul/")
    for skill in result.get("skills_created", []):
        click.echo(f"  Created skill: {skill}")


# ── Attach command groups ─────────────────────────────────────────────

cli.add_command(team_group)
cli.add_command(agent_group)
cli.add_command(msg_group)
cli.add_command(feed_group)
cli.add_command(lock_group)


# ── Entry point ──────────────────────────────────────────────────────


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
