# Phalanx

Open-source, vendor-agnostic multi-agent orchestration CLI.

Phalanx lets you spin up teams of AI coding agents from any supported backend (Cursor, Claude Code, Gemini CLI, Codex CLI) and coordinate them through a single unified interface — with isolated worktrees, shared message feeds, artifact collection, and automatic stall detection.

## Install

```bash
pip install phalanx-cli
# or
uv tool install phalanx-cli
```

Requires: Python 3.11+, tmux, git.

## Backend Authentication (Required)

Before using Phalanx, authenticate each backend CLI you plan to run.
Phalanx can spawn agents non-interactively, so first-run login prompts inside
tmux can block teams if auth has not been completed beforehand.

At minimum, run each backend once and finish its login flow:

```bash
agent
claude
gemini
codex
```

Then re-run Phalanx.

## Quick Start

```bash
phalanx --auto-approve --model gpt-5.4
```

That's it. Phalanx installs its skill into your agent CLI, then launches it. You talk to your agent as usual:

> "Spin up a team of 2 coders and a reviewer to refactor the auth module"

> "Have 3 agents audit the codebase — one for security, one for performance, one for reliability — and give me a consolidated report"

The agent knows phalanx commands via the installed skill. It handles everything: creating the team, assigning tasks, monitoring workers, collecting results, and reporting back. You don't need to memorize any commands.

Flags:
- `--backend` — which agent CLI to launch (`cursor`, `claude`, `gemini`, `codex`). Auto-detected if omitted.
- `--model` — model to use. Optional.
- `--auto-approve` — enable auto-approval of tool calls in the agent.

You can also run phalanx commands directly as a tool (e.g. from an already-running agent session) — see CLI Reference below.

## How It Works

1. **You talk to your agent** — describe what you want in plain language
2. **The agent creates a team** — spawning specialized sub-agents in isolated tmux sessions
3. **Workers run in parallel** — each in its own session, optionally in a separate git worktree
4. **The daemon watches everything** — detects stalls/crashes, pushes real-time events to the team lead
5. **Results flow back** — workers write structured artifacts, team lead consolidates and reports to you

### Event-Driven Coordination

The daemon pushes `[PHALANX EVENT]` notifications to the team lead the moment something happens — a worker finishes, gets stuck, or dies. The lead reacts immediately instead of polling on a timer:

- `worker_done` → read artifact, check if all workers complete
- `worker_blocked` → send a targeted nudge
- `worker_dead` → record failure, decide whether to escalate

### Agent Communication

```bash
phalanx message-agent <agent-id> "focus on the DB layer"   # target one worker
phalanx broadcast <team-id> "wrap up and write artifacts"  # all workers at once
phalanx post "team-id" "status update"                     # write to shared feed
phalanx feed                                               # read the shared feed
```

## Supported Backends

| Backend | Binary | Model Routing |
|---------|--------|---------------|
| Cursor | `agent` | All vendors |
| Claude Code | `claude` | Anthropic |
| Gemini CLI | `gemini` | Google |
| Codex CLI | `codex` | OpenAI |

## Agent Roles

| Role | Purpose |
|------|---------|
| `researcher` | Investigation, large-context analysis |
| `coder` | Implementation, bug fixes, tests |
| `reviewer` | Code review, large diffs |
| `architect` | Design decisions, high-stakes reasoning |

Phalanx automatically selects the best model per role and backend. Configurable in `.phalanx/config.json`.

## Architecture

- **State**: SQLite (WAL mode) at `.phalanx/state.db`
- **Process isolation**: Agents run interactively inside background `tmux` sessions. Output is captured via `pipe-pane` into `stream.log`, enabling screen-scrape-based stall detection without fragile prompt engineering.
- **Real-time messaging**: Because agents run live in `tmux`, Phalanx delivers messages by injecting keystrokes — instant, no session restart required.
- **Event-push daemon**: The per-team monitor daemon detects state changes and pushes structured notifications to the team lead, so the lead is reactive rather than polling.
- **Artifacts**: Structured JSON outputs written by each agent, readable by the lead and the orchestrator.
- **Stall detection**: `stream.log` mtime and content hash are monitored. Idle agents are nudged; timed-out agents are killed and DB state is updated.
- **Spawn stagger**: Backends with startup races (e.g. Cursor's `cli-config.json`) are staggered automatically.
- **GC**: Opportunistic cleanup of dead teams, running on standard CLI commands.

## CLI Reference

### Team Management

| Command | Description |
|---------|-------------|
| `phalanx init` | Initialize `.phalanx/` in workspace |
| `phalanx create-team "task"` | Create a team with a shared task |
| `phalanx create-team --config file.json` | Create a team with per-agent prompts and worktrees |
| `phalanx team-status <id>` | Show team and all agent statuses |
| `phalanx team-result <id>` | Read team lead's final consolidated artifact |
| `phalanx list-teams` | List all teams |
| `phalanx stop <id>` | Stop a team (keep data, resumable) |
| `phalanx resume <id>` | Resume a stopped team |
| `phalanx gc` | Clean up dead teams and old data |

### Monitoring & Messaging

| Command | Description |
|---------|-------------|
| `phalanx status` | Show all running agents across all teams |
| `phalanx agent-status <id>` | Show specific agent status and last heartbeat |
| `phalanx monitor <id>` | Attach a blocking monitoring loop |
| `phalanx message <team-id> "msg"` | Message the team lead |
| `phalanx message-agent <agent-id> "msg"` | Message a specific agent |
| `phalanx broadcast <team-id> "msg"` | Broadcast to all agents in a team |
| `phalanx send-keys <agent-id> <keys>` | Send raw keystrokes to an agent's tmux pane |

### Agent Tools (used by spawned agents)

| Command | Description |
|---------|-------------|
| `phalanx write-artifact --status <s> --output '<json>'` | Write structured result |
| `phalanx agent-result <id>` | Read a peer agent's artifact |
| `phalanx feed` | Read the shared team message feed |
| `phalanx post "msg"` | Post a message to the shared feed |
| `phalanx lock <path>` / `phalanx unlock <path>` | Advisory file locking |

## Configuration

`.phalanx/config.json`:

```json
{
  "default_backend": "codex",
  "idle_timeout_seconds": 1800,
  "max_runtime_seconds": 1800,
  "stall_check_interval": 20,
  "auto_approve": true
}
```

## Develop Locally

```bash
git clone https://github.com/creynir/phalanx.git
cd phalanx
uv sync
uv run pytest tests/
```

## License

MIT
