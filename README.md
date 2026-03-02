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

## Quick Start

Initialize Phalanx in your workspace:

```bash
phalanx init
```

Create a team with a shared task:

```bash
phalanx --auto-approve create-team "refactor the auth module" --agents coder:2,reviewer
```

Or use a per-agent config file for full control:

```bash
phalanx --auto-approve create-team --config team.json
```

Check progress:

```bash
phalanx team-status <team-id>
```

Read the final consolidated result:

```bash
phalanx team-result <team-id>
```

## Per-Agent Config

For distinct tasks per agent, pass a JSON config:

```json
{
  "task": "Audit and improve the payments module",
  "agents": [
    {
      "name": "security-review",
      "role": "reviewer",
      "prompt": "Review phalanx/payments.py for injection and auth issues. Write artifact with findings."
    },
    {
      "name": "perf-coder",
      "role": "coder",
      "prompt": "Profile and optimize the slow paths in phalanx/payments.py. Write artifact with changes made.",
      "worktree": "/path/to/isolated/worktree"
    }
  ]
}
```

Each agent can have its own `worktree` path for full file isolation.

## How It Works

1. **Workers run in isolation** — each agent lives in its own `tmux` session, optionally in a separate git worktree
2. **A team lead coordinates** — monitors worker state, reacts to events, consolidates results
3. **The daemon watches everything** — detects stalls/crashes, pushes real-time events to the team lead
4. **Results flow back** — workers write JSON artifacts, team lead reads and consolidates them

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
  "default_backend": "cursor",
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
