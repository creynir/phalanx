# Phalanx Fix Catalog: v0.3.0 → v0.3.9

Every bug fix and feature shipped since v0.3.0. The spec team MUST produce test
scenarios covering each of these. If a fix isn't tested, the regression will return.

---

## v0.3.1 — Fix worker_done event never reaching team lead

**Bug:** When a worker wrote an artifact, the team monitor never sent a
`[PHALANX EVENT] worker_done` notification to the team lead. The lead had
to poll manually to discover completed workers.

**Root cause:** The monitor checked `artifact_status` on the cached agent
dict from the start of the loop iteration, not a fresh DB read. By the time
the artifact was written, the cached dict was stale.

**Fix:** Added a `db.get_agent()` refresh inside the monitor loop to re-read
`artifact_status` on every poll cycle before comparing.

**Test needed:** Worker writes artifact → monitor detects within 1 poll cycle
→ lead receives `worker_done` event.

---

## v0.3.2 — Add resume-agent command, fix auto_approve on resume

**Feature:** New `phalanx resume-agent <agent-id>` command to restart a
single dead/suspended agent within its team.

**Bug:** When resuming agents, `auto_approve` was not passed to the backend's
resume command. Agents resumed without `--yolo` and immediately hit
permission prompts.

**Fix:** `spawn_resume()` now accepts and injects `auto_approve` flags.

**Tests needed:**
- `phalanx resume-agent` on a suspended agent → restarts successfully
- `phalanx resume-agent` on a running agent → error message
- Resumed agent has `--yolo` flag when `--auto-approve` is set

---

## v0.3.3 — Default launch mode (phalanx without subcommand)

**Feature:** Running `phalanx` without a subcommand now launches an
interactive agent session. It runs `phalanx init` if needed, deploys
skills, then `execvp`s the backend CLI binary.

**Tests needed:**
- `phalanx` with no args → skill init → agent binary launched
- `phalanx --backend cursor --model opus-4.6` → correct flags passed
- `phalanx init` creates `.phalanx/` and deploys skill files

---

## v0.3.4 — Fix false agent_idle detection during active generation

**Bug:** The `agent_idle` stall pattern fired when the Cursor TUI was
actively generating (the "follow-up" bar was visible during generation).
The monitor nudged agents mid-work, causing double-execution.

**Root cause:** The `_check_agent_idle` pattern didn't check for
active-generation indicators like "Generating", "Running", "Thinking".

**Fix:** Added `active_indicators` check — if any of "Generating",
"Running", "Thinking", "ctrl+c to stop", "Waiting for approval" appear
in the tail, `agent_idle` does NOT fire.

**Test needed:** Agent is actively generating → stall detector returns
`None` (no event), NOT `agent_idle`.

---

## v0.3.5 — Fix silent message delivery failure, add configurable timeouts

### Bug 1: message-agent / message / broadcast report success on dead agents

**Bug:** `phalanx message-agent <id> "..."` reported "Message sent" even
when the target agent was dead/suspended. The CLI didn't check agent status
before attempting delivery.

**Fix:** CLI now checks `agent["status"] != "running"` and returns an error
with the agent's actual status and a suggestion to use `resume-agent`.
JSON mode returns `{"ok": false, "delivered": false, "status": "..."}`.

**Tests needed:**
- `message-agent` to a suspended agent → error exit code + status message
- `message-agent` to a running agent → success
- `broadcast` with mix of running/suspended → reports which were skipped
- JSON output mode for all three

### Bug 2: No CLI flags for timeout configuration

**Bug:** `idle_timeout` and `max_runtime` were hardcoded. No way for users
to configure them per-team.

**Fix:** Added `--idle-timeout` and `--max-runtime` flags to `create-team`
and `team-monitor` commands. Removed dead `stall_seconds` / `max_runtime`
DB columns (SCHEMA_VERSION 3→4 migration).

**Tests needed:**
- `create-team --idle-timeout 60` → monitor uses 60s timeout
- Default timeout is 1800s when flag not provided
- DB migration from v3 to v4 drops old columns

---

## v0.3.6 — Fix monitor killing resumed agents

**Bug:** When the team lead called `phalanx resume-agent` on a suspended
worker, the monitor immediately reported the worker as DEAD. The monitor's
ProcessManager didn't know about the new tmux session.

**Root cause:** `process_manager.kill_agent()` removes the agent from the
in-memory dict. When `resume-agent` spawns a new session, the monitor's
ProcessManager still has no entry. `get_process()` returns `None` →
`StallDetector` reports DEAD.

**Fix:** Added re-discovery logic in `team_monitor.py`: if an agent is
`running` in DB but missing from ProcessManager, call
`process_manager.discover_agent()` to find the new tmux session.

**Tests needed:**
- Worker suspended → lead calls resume-agent → monitor re-discovers →
  does NOT report DEAD
- Monitor logs "Re-discovered resumed agent" message

---

## v0.3.7 — Detect connection_lost, auto-restart affected agents

**Bug:** When the Cursor CLI hit "Connection lost. Retry attempted.",
the agent was stuck forever. The stall detector didn't recognize this
pattern, so the agent stayed in `running` status indefinitely.

**Fix:**
1. New `connection_lost` pattern in stall detector matching
   "Connection lost", "connection error", "disconnected", "Session expired"
2. New `_auto_restart_agent` in team_monitor: kills the stuck session,
   marks dead, calls `resume_single_agent`, notifies lead with
   `worker_restarted` event.

**Tests needed:**
- Screen with "Connection lost" → stall detector returns
  `BLOCKED_ON_PROMPT` with `prompt_type="connection_lost"`
- Monitor auto-restarts the agent (kill → dead → resume)
- Lead receives `worker_restarted` notification

---

## v0.3.8 — Fix context loss on agent resume

**Bug:** Resumed agents had zero memory of their prior session. `chat_id`
was never stored in the DB, so every resume was a cold restart with the
original `task.md`. Workers re-did completed work. The lead didn't know
about prior artifacts or team state.

**Root cause:** `parse_chat_id()` existed on all backends but was never
called. Resume always fell through to the `else` branch that replayed
the original prompt.

**Fix:** New `_build_resume_prompt()` function generates a context-enriched
prompt on resume:
- **Lead resume:** includes worker statuses, all worker artifacts, lead's
  own prior artifact, pending messages, and explicit instructions not to
  repeat completed work.
- **Worker resume:** includes the worker's prior artifact with instructions
  to wait for new assignments instead of re-doing the original task.

Also fixed `{worker_list}` / `{team_task}` dead placeholders in
`team_lead.md` — replaced with `{task}` which already contains all info.

**Tests needed:**
- Resume lead after all workers completed → lead sees prior artifacts
- Resume lead → lead does NOT re-send original tasks to completed workers
- Resume worker with artifact → worker does NOT redo original task
- Resume worker without artifact → worker completes original task
- Lead resume prompt contains pending messages from main agent

### Sub-bug: Livelock — lead endlessly resumes completed workers

**Bug:** The soul template told the lead to `resume-agent` on
`worker_timeout` events without checking artifact status. Workers
cold-restarted, re-did their task, went idle, got suspended,
lead resumed them again. Infinite loop.

**Fix:** Resume context now tells the lead: "Do NOT resume workers that
already have successful artifacts unless you have new tasks for them."

**Test needed:** Worker with artifact=success gets suspended → lead does
NOT resume it unless there's new work.

---

## v0.3.9 (this release) — Detect ghost sessions (process_exited)

**Bug:** When the agent binary (Cursor/node) crashes inside a tmux session,
the session falls back to a bare shell (zsh/bash). Phalanx reported the
agent as `running` because `is_alive()` only checked tmux session existence,
not the process inside it.

**Symptoms:**
- Stream.log shows `zsh: command not found: success`, `zsh: command not found: failure`
- Garbled output like `"escalation_r- "escalation_r-` looping
- Bare shell prompt visible in tmux capture-pane
- Agent stays `status=running` indefinitely with no artifact

**Root causes (from postmortem investigation of team-09c54815):**
1. **DEM Expert crash:** Cursor TUI rendering crash while outputting
   "escalation_required" — reproducible on fresh starts. The garbled
   buffer was dumped into zsh as commands.
2. **Team Lead crash:** Long text injected via `tmux send-keys` into an
   active TUI corrupts the input buffer ("If you havIf you hav..." looping).
   Cursor process dies, tmux session stays alive.

**Fix:**
1. `AgentProcess.is_alive()` now checks `pane_current_command` — if the
   foreground process is `zsh`, `bash`, `sh`, `fish`, or `dash`, returns
   `False` even though the tmux session exists.
2. New `process_exited` stall pattern detects:
   - 2+ shell error lines (`zsh:`, `command not found`, `parse error`)
   - Bare shell prompt (`user@host path$`) as last line
3. `process_exited` triggers `_auto_restart_agent` in team_monitor
   (same as `connection_lost`).

**Tests needed:**
- Agent binary exits → `is_alive()` returns `False`
- Screen with `zsh: command not found` × 2 → `process_exited` detected
- Screen with bare shell prompt → `process_exited` detected
- Monitor auto-restarts the ghost agent
- Lead receives `worker_restarted` notification

---

## Cross-cutting issues the spec MUST cover

1. **Message delivery to "done" agents:** Cursor agent stops accepting
   `send_keys` after task completion. The node process is alive but the
   TUI is in a "done" state. Messages are silently dropped. This is NOT
   yet fixed. Tests should verify this behavior and document it.

2. **Prompt injection:** Large multi-line prompts passed inline via
   `shlex.join` + `send_keys` can corrupt the terminal. The shell enters
   `quote>` mode. This works but is fragile. Tests should verify prompts
   with special characters (backticks, single quotes, angle brackets).

3. **Concurrent spawn races:** Cursor agents race on `~/.cursor/cli-config.json`.
   The `spawn_delay()` mechanism (3s stagger) prevents this. Tests should
   verify staggered spawns.

4. **Skill deployment:** `phalanx init` deploys workspace-level rules
   (`.cursor/rules/phalanx.mdc`) and global skills. Tests should verify
   the skill content matches the expected template.
