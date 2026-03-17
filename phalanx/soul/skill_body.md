# Phalanx Multi-Agent Orchestration

You have `phalanx` installed as a CLI tool for managing teams of AI agents.
When the user asks you to parallelize work, delegate tasks, spin up agents,
or do anything that benefits from multiple agents — use phalanx.

## As a WORKER agent (most common)

If you were spawned by phalanx to do a task, you MUST signal completion by running:

```bash
phalanx agent done --output '{"key": "value", "findings": "..."}'
# For failures:
phalanx agent done --output '{"error": "reason"}' --failed
# For escalations:
phalanx agent done --output '{"reason": "needs human input"}' --escalate
```

**This is mandatory.** The team lead and monitor are waiting for your artifact.
Run it as the LAST command after completing your work.

## As a LEAD agent (orchestrator)

### Team & agent commands
```bash
# List all agents in your team and their status
phalanx team status $PHALANX_TEAM_ID

# Check full team status
phalanx team status <team-id>

# Get a specific agent's artifact/result
phalanx agent result <agent-id>

# Send a message to a specific agent
phalanx msg send <agent-id> "instruction"

# Resume a suspended/dead agent
phalanx agent resume <agent-id>

# Stop the whole team
phalanx team stop <team-id>

# Create a new team (if you need to spin up sub-teams)
phalanx team create --task "description" --agents lead,coder:2 --auto-approve
```

### Workflow as lead
1. Check worker status: `phalanx agent list`
2. Wait for workers to complete (artifact_status = success/failure)
3. Read results: `phalanx agent result <agent-id>`
4. Synthesize and write your own artifact: `phalanx agent done --output '{...}'`

## Critical Rules
- **Workers MUST run `phalanx agent done` when finished** — never just stop or idle
- The team lead waits for worker artifacts before synthesizing
- Use `phalanx agent list` to check team progress (not `team status`)
- `PHALANX_AGENT_ID` and `PHALANX_TEAM_ID` env vars are set in your session
