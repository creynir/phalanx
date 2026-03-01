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

Start an agent session and talk to it:

```bash
phalanx                          # interactive session (auto-detects backend)
phalanx -b gemini                # use a specific backend
phalanx run "fix the failing tests"  # with an initial prompt
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

- **State**: SQLite (WAL mode) at `~/.phalanx/state.db`
- **Process isolation**: tmux sessions per agent
- **Artifacts**: Ephemeral JSON (deleted after 24h inactivity)
- **File locking**: Advisory locks via SQLite
- **Stall detection**: stream.log monitoring with exponential backoff retry
- **GC**: Opportunistic, runs on every command

## CLI Reference

### User-Facing

| Command | Description |
|---------|-------------|
| `phalanx` | Start interactive agent session |
| `phalanx run "prompt"` | Single agent session with prompt |
| `phalanx --auto-approve create-team` | Create agent team |
| `phalanx team-status <id>` | Team status |
| `phalanx team-result <id>` | Read team results |
| `phalanx message <id> "msg"` | Message team lead |
| `phalanx stop <id>` | Stop team |
| `phalanx resume <id>` | Resume team |
| `phalanx status` | List all teams |
| `phalanx config show/set` | Configuration |
| `phalanx models show/set/reset/update` | Model routing |

### Agent Tools (used by spawned agents)

| Command | Description |
|---------|-------------|
| `phalanx write-artifact` | Write structured result |
| `phalanx agent-status` | Check peer status |
| `phalanx agent-result <id>` | Read peer artifact |
| `phalanx message <team-id> "msg"` | Message team lead |
| `phalanx message-agent <id> "msg"` | Message a specific worker |
| `phalanx lock/unlock <path>` | File locking |

## Develop Locally

```bash
git clone https://github.com/creynir/phalanx.git
cd phalanx
pip install -e ".[dev]"
```

Run tests:

```bash
pytest tests/unit/          # unit tests
pytest tests/integration/   # integration tests (requires tmux)
pytest tests/e2e/           # end-to-end tests
pytest tests/               # all 211 tests
```

Pre-commit hooks (ruff lint + format) are configured — install with:

```bash
pip install pre-commit
pre-commit install
```

## Configuration

Global: `~/.phalanx/config.toml`
Workspace override: `.phalanx/config.toml`

```toml
[defaults]
backend = "cursor"

[timeouts]
agent_inactivity_minutes = 30
team_gc_hours = 24
stall_seconds = 180

[models.cursor]
orchestrator = "sonnet-4.6"
coder = "sonnet-4.6"
researcher = "gemini-3.1-pro"
default = "gemini-3.1-pro"
```

## License

MIT
