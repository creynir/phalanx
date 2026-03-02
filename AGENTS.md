# Phalanx Multi-Agent Orchestration

You have `phalanx` installed as a CLI tool for managing teams of AI agents.
When the user asks you to parallelize work, delegate tasks, spin up agents,
or do anything that benefits from multiple agents — use phalanx.

## Creating a Team

### Step 1: Write a team config JSON file

Create a JSON config file with per-agent prompts. Each agent gets a unique,
detailed prompt describing its specific role and task.

```json
{
  "task": "Overall team objective — what the team is trying to achieve",
  "lead": {
    "name": "team-lead",
    "model": "claude-sonnet-4-20250514"
  },
  "agents": [
    {
      "name": "security-reviewer",
      "role": "reviewer",
      "prompt": "You are the SECURITY REVIEWER. Your job is to...",
      "model": "claude-sonnet-4-20250514"
    },
    {
      "name": "performance-analyst",
      "role": "researcher",
      "prompt": "You are the PERFORMANCE ANALYST. Your job is to...",
      "model": "claude-sonnet-4-20250514"
    }
  ]
}
```

**Agent roles**: `researcher`, `coder`, `reviewer`, `architect`
**Models**: Set per agent, or omit to use default for the role/backend.

Write detailed, specific prompts for each agent. Include:
- Their role identity and expertise
- Files to read for context (use absolute paths)
- Specific instructions for their task
- How to interact with teammates (via team feed)
- What to include in their artifact

### Step 2: Create the team

```bash
phalanx --auto-approve create-team --config /path/to/team.json --json
```

This spawns all agents with their unique prompts + a team lead + a monitoring daemon.
Returns team_id, lead_id, and worker_ids.

### Quick mode (same prompt for all workers)

For simple tasks where all workers do the same thing:
```bash
phalanx --auto-approve create-team "task description" --agents coder:3 --json
```

## Team Lifecycle

### Check status (user-driven — do NOT poll in a loop)
```bash
phalanx team-status <team-id> --json
```

### Get results when complete
```bash
phalanx team-result <team-id> --json          # Team lead's consolidated artifact
phalanx agent-result <agent-id> --json        # Specific worker's artifact
```

### Send message to team lead
```bash
phalanx message <team-id> "instruction"
```

### Send message to a specific worker
```bash
phalanx message-agent <agent-id> "instruction"
```

### Broadcast to all agents in a team
```bash
phalanx broadcast <team-id> "instruction"
```

### Resume a stopped/dead team
```bash
phalanx resume <team-id>              # Restart team lead only
phalanx resume <team-id> --all-agents # Restart all dead agents
```

### Stop and clean up
```bash
phalanx stop <team-id>
```

### List all teams
```bash
phalanx status --json
```

## Workflow
1. Write team config JSON with per-agent prompts
2. Create team: `phalanx --auto-approve create-team --config team.json --json`
3. Wait for user to ask about status, then: `phalanx team-status <team-id> --json`
4. Steer the team: `phalanx message <team-id> "focus on X"` or message individual agents
5. Read results: `phalanx team-result <team-id> --json` or per-agent: `phalanx agent-result <agent-id> --json`
6. **Persist results yourself** — write important findings to workspace files
7. Clean up: `phalanx stop <team-id>`

## Critical Rules
- Team artifacts are **EPHEMERAL** — deleted after 24h of inactivity
- Always persist important results to workspace files yourself
- Use `--worktree` when agents modify shared files to avoid conflicts
- All commands support `--json` for structured output
- Sub-agents run autonomously with full permissions in isolated sessions
- **Do NOT poll team-status in a loop** — it blocks your session. Check when the user asks.
- **Do NOT read stream.log files** — status flows through team-status and team lead
- **Long messages (>500 chars)**: write content to a file, then message the agent to read it
- **If team lead dies**: use `phalanx resume <team-id>` to restart it

## Team Feed
Agents communicate via a shared team feed (SQLite-backed, concurrent-safe):
- Agents post with `phalanx post "message"`
- Agents read with `phalanx feed`
- You (Main Agent) can read it too: `phalanx feed --team-id <team-id>`
