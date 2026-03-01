# Phalanx

Open-source, vendor-agnostic multi-agent orchestration CLI.

Phalanx lets you spin up teams of AI coding agents from any supported backend (Cursor, Claude Code, Gemini CLI, Codex CLI) and orchestrate them through a single unified interface.

## Install

```bash
pip install -e ".[dev]"
```

Requires: Python 3.11+, tmux.

## Quick Start

```bash
# Single agent (proxies to your default backend)
phalanx run "fix the failing tests"

# Create a team of agents
phalanx create-team --task "refactor auth module" --agents researcher,coder:2,reviewer --json

# Check team status
phalanx team-status <team-id> --json

# Read results
phalanx team-result <team-id> --json

# Stop when done
phalanx stop <team-id>
```

## IDE Integration

```bash
phalanx init
```

Auto-detects installed IDEs and deploys skill files:
- **Cursor**: `.cursor/rules/phalanx.mdc`
- **Claude Code**: `.claude/commands/phalanx.md`
- **Gemini CLI**: `.gemini/phalanx-policy.md`
- **Codex CLI**: `AGENTS.md`

## Supported Backends

| Backend | Binary | Worktree | Model Routing |
|---------|--------|----------|---------------|
| Cursor | `agent` | Native | All vendors |
| Claude Code | `claude` | Native | Anthropic |
| Gemini CLI | `gemini` | Phalanx-managed | Google |
| Codex CLI | `codex` | Phalanx-managed | OpenAI |

## Model Routing

Phalanx automatically selects the best model per agent role and backend. Configurable in `~/.phalanx/config.toml`.

```bash
phalanx models show           # view routing table
phalanx models set cursor.coder opus-4.6  # override
phalanx models reset           # restore defaults
```

## Agent Roles

| Role | Purpose |
|------|---------|
| `researcher` | Investigation, large-context analysis |
| `coder` | Implementation, bug fixes, tests |
| `reviewer` | Code review, large diffs |
| `architect` | Design decisions, high-stakes reasoning |
| `orchestrator` | Team lead (auto-assigned) |

## Architecture

- **State**: SQLite (WAL mode) at `~/.phalanx/state.db`
- **Process isolation**: tmux sessions per agent
- **Artifacts**: Ephemeral JSON (deleted after 24h inactivity)
- **File locking**: Advisory locks via SQLite
- **Stall detection**: stream.log monitoring with exponential backoff retry
- **GC**: Opportunistic, runs on every command

## Commands

### User-Facing
| Command | Description |
|---------|-------------|
| `phalanx run "prompt"` | Single agent session |
| `phalanx init` | Deploy IDE skill files |
| `phalanx create-team` | Create agent team |
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
| `phalanx message-agent <id> "msg"` | Message a worker |
| `phalanx lock/unlock <path>` | File locking |

## Testing

```bash
pytest tests/unit/          # 125 unit tests
pytest tests/integration/   # 26 integration tests (requires tmux)
pytest tests/e2e/           # 11 end-to-end tests
pytest tests/               # all 162 tests
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
