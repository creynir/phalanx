# Phalanx

Open-source, vendor-agnostic multi-agent orchestration CLI.

Phalanx lets you spin up teams of AI coding agents from any supported backend (Cursor, Claude Code, Gemini CLI, Codex CLI) and orchestrate them through a single unified interface. You talk to your agent naturally — it handles the rest.

## Install

```bash
pip install phalanx-cli
# or
pipx install phalanx-cli
```

Requires: Python 3.11+, tmux.

## Quick Start

Initialize Phalanx in your workspace:

```bash
phalanx init
```

Start an agent session and talk to it:

```bash
phalanx run-agent "fix the failing tests"
```

Then just ask your agent to create teams:

> "Spin up a team of 2 coders and a reviewer to refactor the auth module"

The agent knows how to use phalanx — it will create the team, monitor progress, collect results, and report back. You don't need to memorize any commands.

## How It Works

1. **You talk to your agent** — via `phalanx run` or your IDE (Cursor, Claude Code, etc.)
2. **The agent creates teams** — spawning sub-agents in isolated tmux sessions
3. **Agents communicate** — the main agent can message the team lead or any individual worker
4. **Results flow back** — agents write artifacts, main agent reads and persists them

### Agent Communication

A key feature: agents don't just fire-and-forget. The main agent can:

- **Message the team lead**: steer direction, ask for status updates, change priorities
- **Message individual workers**: give specific feedback, request changes, unblock them
- **Read artifacts**: check each agent's output as it becomes available
- **Monitor health**: detect stalled or dead agents, retry automatically

This creates a true collaborative workflow, not just parallel execution.

## Supported Backends

| Backend | Binary | Worktree | Model Routing |
|---------|--------|----------|---------------|
| Cursor | `agent` | Native | All vendors |
| Claude Code | `claude` | Native | Anthropic |
| Gemini CLI | `gemini` | Phalanx-managed | Google |
| Codex CLI | `codex` | Phalanx-managed | OpenAI |

## Agent Roles

| Role | Purpose |
|------|---------|
| `researcher` | Investigation, large-context analysis |
| `coder` | Implementation, bug fixes, tests |
| `reviewer` | Code review, large diffs |
| `architect` | Design decisions, high-stakes reasoning |
| `orchestrator` | Team lead (auto-assigned) |

Phalanx automatically selects the best model per role and backend. Configurable in `~/.phalanx/config.toml`.

## Model Routing

```bash
phalanx models show                        # view routing table
phalanx models set cursor.coder opus-4.6   # override a role
phalanx models reset                       # restore defaults
```

## Architecture

- **State**: SQLite (WAL mode) at `.phalanx/state.db`
- **TUI Process Isolation**: Agents run interactively inside background `tmux` sessions. Output is captured via `pipe-pane`, meaning Phalanx can screen-scrape and deterministically handle CLI prompts (like workspace trust or tool approval) without relying on fragile prompt engineering.
- **Real-Time Communication**: Because agents are running live in `tmux`, Phalanx can send them keystrokes or interrupt them (`Ctrl+C`) to deliver messages instantly, instead of relying on slow, costly session restarts via `--resume`.
- **Artifacts**: Ephemeral JSON storing structured outputs per agent.
- **Stall Detection**: `stream.log` (from `tmux`) is monitored via a Heartbeat system. If an agent hangs or crashes, Phalanx detects the lack of output, interrupts, and prompts the agent to continue or fail gracefully.
- **GC**: Opportunistic cleanup of dead teams, running on standard CLI commands.

## CLI Reference

### User-Facing

| Command | Description |
|---------|-------------|
| `phalanx init` | Initialize `.phalanx` in workspace, generate skill files |
| `phalanx run-agent "task"` | Spawn a single interactive agent (no team lead) |
| `phalanx create-team "task"` | Create a team and start its team lead |
| `phalanx monitor <id>` | Attach a blocking DEM-style monitoring loop |
| `phalanx team-status [id]` | View team status summary |
| `phalanx agent-status [id]` | View specific agent status |
| `phalanx team-result <id>` | Read team lead's final artifact |
| `phalanx message <id> "msg"` | Message a team lead |
| `phalanx message-agent <id> "msg"` | Message a specific agent |
| `phalanx send-keys <id> <keys>` | Send raw keystrokes to an agent's `tmux` pane |
| `phalanx stop <id>` | Stop a team (kills processes) |
| `phalanx status` | List all running agents across all teams |
| `phalanx gc` | Clean up old data and dead teams |

### Agent Tools (used by spawned agents)

| Command | Description |
|---------|-------------|
| `phalanx spawn-agent` | Spawn a sub-agent (used by team lead) |
| `phalanx write-artifact` | Write structured result (success/failure/escalation) |
| `phalanx agent-result <id>` | Read peer artifact |
| `phalanx lock/unlock <path>` | Advisory file locking to prevent collisions |

## Develop Locally

```bash
git clone https://github.com/creynir/phalanx.git
cd phalanx
uv sync
uv pip install -e ".[dev]"
```

Run tests:

```bash
uv run pytest tests/
```

## Configuration

Workspace overrides can be edited at `.phalanx/config.json`:

```json
{
  "default_backend": "cursor",
  "idle_timeout_seconds": 1800,
  "max_runtime_seconds": 1800,
  "stall_check_interval": 20,
  "auto_approve": true
}
```

## License

MIT
