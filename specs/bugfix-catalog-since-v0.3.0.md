# Phalanx Bugfix & Feature Catalog: v0.3.0 → v0.3.9

All specs and test scenarios MUST cover these cases. Every bug listed here was found in production.

---

## v0.3.1 — worker_done event never reaching team lead

**Bug**: When a worker wrote an artifact, the daemon's heartbeat check did not detect the `artifact_status` change in the DB in time. The team lead never received `[PHALANX EVENT] worker_done` notifications.

**Fix**: The team monitor now checks `artifact_status` on every poll cycle independently of stall events, comparing previous vs current status and sending `worker_done` if it flipped to `success`.

**Test must verify**: Worker writes artifact → lead receives `worker_done` event within one poll cycle.

---

## v0.3.2 — resume-agent command + auto_approve on resume

**Bug**: No way to resume a single dead/suspended agent. `phalanx resume` only restarted the team lead. Also, `--auto-approve` flag was not passed through to resumed agents.

**Fix**: Added `phalanx resume-agent <agent-id>` CLI command and `resume_single_agent()`. Wired `auto_approve` into `spawn_resume()`.

**Test must verify**: `resume-agent` works for both workers and leads. Resumed agent gets `--yolo` flag when `--auto-approve` is set on the parent command.

---

## v0.3.3 — default launch mode

**Feature**: Running `phalanx` without a subcommand now launches an interactive agent session. It runs `phalanx init` if needed, deploys skills, and `execvp`s the backend CLI.

**Test must verify**: `phalanx` without args detects backend, runs init, and execs. Skill files are deployed to workspace.

---

## v0.3.4 — false agent_idle detection during active generation

**Bug**: The `agent_idle` stall pattern fired while agents were actively generating — the TUI showed "→ Add a follow-up" chrome while the agent was still working. This caused the daemon to nudge agents that were mid-task.

**Fix**: Added `active_indicators` check (`Generating`, `Running`, `Thinking`, `ctrl+c to stop`, `Waiting for approval`) — if any are present in the tail, `agent_idle` returns `False`.

**Test must verify**: Agent actively generating → `agent_idle` returns `False`. Agent truly idle at prompt → `agent_idle` returns `True`. Agent with artifact at prompt → `agent_idle` is suppressed.

---

## v0.3.5 — silent message delivery failure + configurable timeouts

**Bug 1**: `phalanx message-agent` / `message` / `broadcast` reported "Message sent" even when the target agent was dead/suspended (tmux session gone). Messages went to dead sessions silently.

**Fix**: CLI checks `agent["status"] != "running"` before delivery. Returns error with agent status and suggests `resume-agent`. JSON mode returns `ok: false`.

**Bug 2**: `broadcast` didn't name which agents were skipped.

**Fix**: Output now lists `Skipped: agent-id (suspended), ...`. JSON includes `skipped` dict.

**Bug 3**: Agent timeouts were hardcoded. `stall_seconds` and `max_runtime` columns in DB were never read.

**Fix**: Added `--idle-timeout` and `--max-runtime` CLI flags to `create-team` and `team-monitor`. Removed dead DB columns. Values passed via CLI to the daemon process.

**Bug 4**: `defaults/config.toml` had wrong timeout values vs `PhalanxConfig` defaults.

**Fix**: Deleted the unreferenced file.

**Tests must verify**:
- `message-agent` to suspended agent → error, not success
- `broadcast` with mix of running/suspended → correct skip reporting
- `--idle-timeout 60` → agent suspended after 60s of idle
- `--max-runtime 120` → agent killed after 120s total

---

## v0.3.6 — monitor killing resumed agents

**Bug**: When the team lead called `phalanx resume-agent` on a suspended worker, the monitor's `ProcessManager` didn't know about the new tmux session. On the next poll, `get_process()` returned `None` → stall detector reported `DEAD` → worker immediately killed again.

**Fix**: Added re-discovery logic in `team_monitor.py`: if an agent is `running` in DB but missing from `ProcessManager`, call `discover_agent()` to pick up the new tmux session.

**Test must verify**: Lead resumes worker → monitor discovers new session → worker stays alive.

---

## v0.3.7 — connection_lost detection and auto-restart

**Bug**: When Cursor CLI showed "Connection lost. Retry attempted." the agent was stuck forever. No stall pattern matched it.

**Fix**: New `connection_lost` pattern in `stall.py` matching `Connection lost`, `connection error`, `disconnected`, `Session expired`. New `_auto_restart_agent` in `team_monitor.py` kills the stuck session, marks dead, calls `resume_single_agent`, notifies lead.

**Test must verify**: Agent shows "Connection lost" → daemon detects → kills → resumes → lead notified `worker_restarted`.

---

## v0.3.8 — context loss on agent resume

**Bug**: `chat_id` was never stored in the DB. `parse_chat_id()` existed on all backends but was never called. Every resume was a cold restart with the original `task.md` — zero memory of previous work.

**Consequences**:
- Lead re-sent Round 1 instructions instead of Round 2
- Workers re-did completed work
- Livelock: lead kept resuming completed workers who kept re-doing same task

**Fix**: New `_build_resume_prompt()` in `orchestrator.py`. Leads get: worker statuses, all previous artifacts, own artifact, pending messages, and explicit "DO NOT repeat work" instructions. Workers get: their previous artifact and "wait for new assignment" instructions.

**Also fixed**: `{worker_list}` and `{team_task}` placeholders in `team_lead.md` were never substituted. Removed them, using `{task}` which already contains all info.

**Tests must verify**:
- Resume lead after Round 1 → prompt includes worker artifacts and statuses
- Resume worker with existing artifact → prompt says "do NOT redo"
- Lead reads pending messages from resume context
- Lead does NOT blindly resume workers with successful artifacts

---

## v0.3.9 — ghost session detection (process died inside tmux)

**Bug**: When a Cursor agent process crashed (OOM, rendering bug, etc.), the tmux session stayed alive with a bare shell prompt. `is_alive()` checked tmux session existence, not process health. Agent appeared `status=running` forever.

**Evidence from team-09c54815**:
- DEM Expert: Cursor crashed while rendering "escalation_required", dumped garbled buffer into zsh → `zsh: command not found: success` / `failure` / `##`
- Team Lead: Cursor process died on startup from send_keys buffer corruption, left bare bash prompt
- Both stuck at `status=running` indefinitely

**Fix (two layers)**:
1. `is_alive()` now checks `pane_current_command` — if it's `zsh`/`bash`/`sh`/`fish`/`dash`, returns `False`
2. New `process_exited` stall pattern: detects 2+ shell errors (`command not found`, `parse error`) OR bare shell prompt (`user@host dir$`) in screen scrape
3. `process_exited` triggers `_auto_restart_agent` (same as `connection_lost`)

**Tests must verify**:
- Agent process dies → `is_alive()` returns `False` (pane shows shell)
- Screen with `zsh: command not found` errors → `process_exited` detected
- Screen with bare shell prompt → `process_exited` detected
- Ghost session → daemon auto-restarts agent
- Normal agent (node process alive) → `is_alive()` returns `True`, no false positive

---

## Cross-cutting issues found during testing

### Cursor CLI stops accepting send_keys after task completion
When a Cursor agent finishes its task and outputs "No further action needed", the TUI enters a "done" state. `send_keys` text appears in the pane but is never processed. The node process is alive but not reading stdin. This means `message-agent` to a completed-but-not-suspended agent silently fails.

**Status**: Known issue, no fix yet. Workaround: resume worker with new task in prompt, don't rely on message-agent after completion.

### Livelock: lead endlessly resumes completed workers
The `team_lead.md` soul template says "try to restart" on `worker_timeout`. But if the worker already has a success artifact, restarting just re-does the same work → idle timeout → lead resumes again → infinite loop.

**Partial fix in v0.3.8**: Resume context now tells lead "Do NOT resume workers that already have successful artifacts unless you have new tasks." But this is a prompt-level fix, not a system-level guarantee.

### Large prompts via tmux send_keys
Prompts over ~4KB passed inline via `shlex.join` + `send_keys` cause shell quoting chaos. The shell enters `quote>` mode and processes the text character by character. This works (eventually the closing quote arrives) but produces garbled stream.log output and is fragile.

### chat_id never stored
`parse_chat_id()` exists on all 4 backends but is never called anywhere. The `--resume <chat_id>` path in backends works but is dead code. If we ever implement chat_id storage, resumed agents would get full conversation context instead of a reconstructed prompt.
