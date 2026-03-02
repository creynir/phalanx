# Phalanx Project Handoff

This document contains facts, findings, and identified issues from the current codebase state to aid the next agent session in planning and executing refactoring. 

## 1. Current Architecture Facts
- **Execution:** Agents run in interactive TUI mode inside isolated `tmux` sessions.
- **Monitoring:** `tmux pipe-pane` streams the UI to `stream.log`, which is monitored by a Python heartbeat detector.
- **Messaging:** `phalanx message-agent` interrupts busy agents (via `Ctrl+C`) and injects text directly into the `tmux` pane via `tmux send-keys`. Large messages (>500 chars) are written to a temp file, and the agent is instructed to read that file.
- **State:** SQLite (`state.db`) is used for tracking teams, agent status, and file locks.

## 2. Identified Issues & Redundancies

### A. The `messages` Table in SQLite is Dead Code
- **Fact:** In Phase 1, messages were queued in SQLite and agents restarted with `--resume` to read them. 
- **Fact:** In Phase 3 (current TUI mode), messages are injected in real-time via `tmux send-keys`.
- **Issue:** The `messages` table in `phalanx/db.py` (and related methods like `send_message`, `get_pending_messages`) is no longer read by the agents. It is a redundant vestige.

### B. Problematic / Unused CLI Commands
- **`run-agent`:** This command is designed for single-agent use but runs synchronously (blocks the terminal). If the Main Agent executes it, the Main Agent freezes waiting for it to complete.
- **`spawn-agent`:** This command is designed to add a worker to an existing team. However, the current `team_lead.md` prompt explicitly forbids the Team Lead from spawning new agents. Furthermore, `spawn-agent` is not exposed in `skill_body.md`. As a result, it is currently dead code that no agent uses.

### C. The `create-team` Prompt Flaw
- **Fact:** When `phalanx create-team --task "build a web server" --agents coder:3` is executed, the system spawns 1 Team Lead and 3 Workers simultaneously.
- **Issue:** All 3 Worker agents are initialized with the exact same base `worker.md` soul file and the exact same overarching `--task "build a web server"` prompt. 
- **Impact:** There is currently no mechanism during team creation to assign *different*, specific sub-task prompts to individual workers. They all start with identical context.

### D. Cursor CLI Global Rule Support
- **Fact:** A test was conducted to see if Cursor CLI (`agent` binary) running in TUI mode respects global rules (e.g., `~/.cursor/rules/phalanx.mdc` or `~/.cursorrules`).
- **Finding:** It does *not*. Cursor CLI in TUI mode strictly requires the rule file to be in the local project workspace (`.cursor/rules/phalanx.mdc`). 
- **Impact:** The workspace initialization logic in `phalanx/init_cmd.py` that copies the rule into the local `.cursor/rules` folder must be preserved; we cannot rely on a global fallback.

## 3. Pending Refactoring Plan (Discussed)
1. **DB Cleanup:** Remove the `messages` table and associated queuing logic from `db.py` and `cli.py`. Bump the DB schema version and drop the table.
2. **Command Cleanup:** Remove `run-agent` and `spawn-agent` commands and their related logic from the codebase to reduce clutter.
3. **Address Prompt Flaw:** Design a solution for the `create-team` identical prompt issue (to be decided in the next session).
4. **Testing:** Update unit/integration tests to reflect the removed CLI commands and DB tables, and run the full `uv run pytest` suite.
