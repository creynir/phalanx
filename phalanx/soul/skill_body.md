# Phalanx Multi-Agent Orchestration

You have `phalanx` installed as a CLI tool for managing teams of AI agents.
When the user asks you to parallelize work, delegate tasks, spin up agents,
or do anything that benefits from multiple agents — use phalanx.

## Available Tools (shell commands)

### Team lifecycle
```bash
# Create a team (--auto-approve is REQUIRED, always include it)
phalanx --auto-approve create-team --task "description" --agents <role>[:<count>],... [--worktree] --json

# Check team progress
phalanx team-status <team-id> --json

# Get results when complete
phalanx team-result <team-id> --json

# Send a message to team lead
phalanx message <team-id> "instruction"

# Stop and clean up
phalanx stop <team-id>

# Resume a stopped team
phalanx resume <team-id>

# List all teams
phalanx status --json
```

### Agent roles
Available roles: `researcher`, `coder`, `reviewer`, `architect`
Phalanx picks the optimal model for each role automatically.
Example: `--agents researcher,coder:2,reviewer`

## Workflow
1. Create team: `phalanx --auto-approve create-team --task "..." --agents researcher,coder:2 --json`
2. Poll status: `phalanx team-status <team-id> --json` (every 30-60s)
3. Read results: `phalanx team-result <team-id> --json`
4. **Persist results yourself** — write important findings to workspace files
5. Clean up: `phalanx stop <team-id>`

## Critical Rules
- Team artifacts are **EPHEMERAL** — deleted after 24h of inactivity
- Always persist important results to workspace files yourself
- Use `--worktree` when agents modify shared files to avoid conflicts
- All commands support `--json` for structured output
- Sub-agents run autonomously with full permissions in isolated sessions
