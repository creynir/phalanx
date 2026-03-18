# Phalanx

Vendor-agnostic multi-agent orchestration CLI — spin up parallel AI coding teams from a single command.

Runs on your existing Claude, Codex, and Gemini subscriptions — no API keys, no per-token billing.

## Why Phalanx?

Different AI providers have different strengths and different subscription limits. Mixing them in a structured team — one provider handling volume coding work, another handling review and judgment calls — is more efficient than routing everything through a single tool.

Phalanx lets you route work to whichever provider fits. Codex for implementation, Opus for review, Sonnet for orchestration. Each agent in a team can use a different backend and model.

Phalanx v2 was built using phalanx teams.

## Install

```bash
uv tool install phalanx-cli
```

Requires: Python 3.11+, tmux, git.

## Quick Start

```bash
# Initialize phalanx in your workspace
phalanx init

# Launch your agent with phalanx skills installed
phalanx --auto-approve --backend claude --model claude-opus-4-6

# Or create a team directly from a config file
phalanx team create --config team.json
```

Once launched, your agent knows all phalanx commands via an installed skill. Describe what you want in plain language and the agent handles team creation, task delegation, monitoring, and result consolidation.

## How It Works

1. **You describe a goal** — in plain language to your agent, or via a config file
2. **Phalanx spawns a team** — lead and workers run in isolated tmux sessions, optionally in separate git worktrees
3. **The daemon watches** — detects stalls, crashes, and completions; pushes `[PHALANX EVENT]` notifications to the team lead
4. **The lead reacts** — immediately reads worker artifacts, sends nudges, restarts dead agents
5. **Results flow back** — workers write structured artifacts; the lead consolidates and writes a final team artifact

State is stored in SQLite (WAL mode) at `.phalanx/state.db`.

## Team Config

Use `phalanx team create --example` to print a valid v2 config:

```json
{
  "lead": {
    "model": "sonnet-4.6",
    "prompt": "You are the team lead. Delegate tasks to agents and synthesize results.",
    "backend": "claude"
  },
  "agents": [
    {
      "model": "gtp-5.3-codex",
      "prompt": "Implement the feature described by the lead.",
      "backend": "codex"
    },
    {
      "model": "opus-4.6",
      "prompt": "Review the implementation for correctness, security issues, and spec compliance.",
      "backend": "claude",
      "soul": "path/to/reviewer-soul.md",
    }
  ],
  "idle_timeout": 1800,
  "max_runtime": 3600
}
```

**Fields:**

| Field | Description |
|-------|-------------|
| `lead.model` | Model for the team lead |
| `lead.prompt` | Task/instruction for the team lead |
| `lead.backend` | Backend to run the lead on |
| `lead.soul` | (Optional) Path to a custom soul file for the lead |
| `agents[].model` | Model for this worker agent |
| `agents[].prompt` | Task/instruction for this worker |
| `agents[].backend` | Backend to run this worker on |
| `agents[].soul` | (Optional) Path to a custom soul file for this worker |
| `idle_timeout` | Seconds before an idle agent is considered stalled (default 1800) |
| `max_runtime` | Hard cap in seconds before a team is killed (default 3600) |

Mix backends freely — each agent in a team can use a different backend and model.

## Works with codebones

[codebones](https://github.com/creynir/codebones) generates structural context summaries of your codebase — AST tree and function signatures — so agents arrive at their task already knowing where things are, without burning tokens on code discovery.

```bash
# Generate a structural map before running your team
codebones pack --no-files . --max-tokens 40000 > skeleton.md
# Then reference it in your agent prompts
```

Install codebones alongside phalanx for multi-agent workflows on real codebases.

## Soul System

A *soul* is a markdown prompt file that defines an agent's role, tools, and behavioral rules. Phalanx injects the soul as a preamble before the agent's task prompt.

**Built-in souls:**

| Role | File | Used for |
|------|------|----------|
| `lead` | `phalanx/soul/team_lead.md` | Team lead agents |
| `agent` | `phalanx/soul/agent.md` | Worker agents |

Built-in souls are applied automatically based on role. They define event-reactive behavior for the lead (reacting to `[PHALANX EVENT]` notifications) and task-completion discipline for workers.

**Custom soul:** Add a `soul` field to any `lead` or `agents[]` entry in your config pointing to a markdown file. Phalanx will use it in place of the built-in soul. You can also drop a `.phalanx/soul/` directory into your workspace to override built-ins project-wide.

## Backends

| Backend | Binary | Provider |
|---------|--------|----------|
| `cursor` | `agent` | All vendors (model-routed) |
| `claude` | `claude` | Anthropic |
| `codex` | `codex` | OpenAI |
| `gemini` | `gemini` | Google |

**Authentication:** Each backend CLI must be authenticated before Phalanx can spawn agents non-interactively. Run each binary at least once and complete its login flow before using it with Phalanx.

**Auto-approve:** Pass `--auto-approve` to `phalanx team create` (or set it in your top-level launch) to enable non-interactive tool-call approval for spawned agents. Each backend exposes this differently under the hood; Phalanx handles the translation automatically.

## Command Reference

### `phalanx team`

| Command | Description |
|---------|-------------|
| `phalanx team create --config file.json` | Create a team from a v2 JSON config |
| `phalanx team create --task "..."` | Create a team with a shared task string |
| `phalanx team create --example` | Print a valid v2 config example and exit |
| `phalanx team list` | List all teams with status summary |
| `phalanx team status <team-id>` | Show team and all agent statuses |
| `phalanx team result <team-id>` | Read the team lead's consolidated artifact |
| `phalanx team stop <team-id>` | Kill team processes, keep data (resumable) |
| `phalanx team resume <team-id>` | Resume a stopped or dead team |
| `phalanx team broadcast <team-id> "msg"` | Send a message to all agents in a team |
| `phalanx team monitor <team-id>` | Run the per-team monitoring daemon |
| `phalanx team gc` | Clean up dead teams and stale data |

### `phalanx agent`

| Command | Description |
|---------|-------------|
| `phalanx agent status [agent-id]` | Show agent status and last heartbeat |
| `phalanx agent result <agent-id>` | Read an agent's artifact |
| `phalanx agent done --output '<json>'` | Write artifact and mark task complete |
| `phalanx agent done --failed --output '<json>'` | Write artifact with failure status |
| `phalanx agent done --escalate --output '<json>'` | Write artifact requesting escalation |
| `phalanx agent stop <agent-id>` | Stop a specific agent |
| `phalanx agent resume <agent-id>` | Resume a stopped or blocked agent |
| `phalanx agent monitor <agent-id>` | Blocking monitor loop for one agent |
| `phalanx agent logs <agent-id>` | Tail the stream log for an agent |
| `phalanx agent keys <agent-id> <keys>` | Send raw keystrokes to an agent's tmux pane |
| `phalanx agent models --backend <b>` | List available models for a backend |

### `phalanx msg`

| Command | Description |
|---------|-------------|
| `phalanx msg lead <team-id> "msg"` | Send a message to the team lead |
| `phalanx msg agent <agent-id> "msg"` | Send a message to a specific agent |

### `phalanx feed`

| Command | Description |
|---------|-------------|
| `phalanx feed read` | Read the shared team feed |
| `phalanx feed post "msg"` | Post a message to the shared team feed |

### `phalanx lock`

| Command | Description |
|---------|-------------|
| `phalanx lock acquire <file-path>` | Acquire an advisory lock on a file |
| `phalanx lock release <file-path>` | Release an advisory lock on a file |
| `phalanx lock status` | Show all active file locks |

### Top-level

| Command | Description |
|---------|-------------|
| `phalanx init` | Initialize `.phalanx/` in the current workspace |
| `phalanx --backend <b> --model <m>` | Launch your agent with phalanx skills installed |

## Develop

```bash
git clone https://github.com/creynir/phalanx.git
cd phalanx
uv sync
uv run pytest tests/
```

## License

MIT
