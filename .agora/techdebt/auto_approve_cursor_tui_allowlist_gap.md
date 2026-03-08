# Auto-Approve / Cursor TUI Allowlist Gap — Root Cause Trace

## Summary

When `phalanx --auto-approve create-team` is used, Phalanx adds `--yolo` to the Cursor agent command. This enables **Phalanx-level** message/tool approval (agents auto-accept). However, **Cursor TUI** has a separate shell command allowlist. Commands like `cd`, `ls`, `which` are not in the allowlist by default, so agents get stuck on "Waiting for approval... Not in allowlist". The only workaround is manually sending Shift+Tab (BTab) to each tmux session to enable "Run Everything" in Cursor's TUI.

**Root cause:** Phalanx never sends the BTab keystroke after spawning. There is no mechanism to auto-enable Cursor's "Run Everything" mode.

---

## 1. How Agents Are Spawned

### Entry point: `phalanx create-team`

**File:** `apps/cli/src/phalanx/cli.py`  
**Lines:** 170–264

- `--auto-approve` is a **root-level** option (line 77) and stored in `ctx.obj["auto_approve"]`.
- `create_team_cmd` reads it at line 201:  
  `auto_approve = ctx.obj.get("auto_approve", False)`
- Passed to `create_team_from_config()` or `create_team()` depending on `--config`.

### Team creation: `create_team` / `create_team_from_config`

**File:** `apps/cli/src/phalanx/team/create.py`

- `create_team` (lines 133–224): Parses `agents_spec`, spawns workers then lead via `spawn_agent()`.
- `create_team_from_config` (lines 51–130): Spawns each agent from config via `spawn_agent()`.
- All call `spawn_agent(..., auto_approve=auto_approve)`.

### Spawn orchestration: `spawn_agent`

**File:** `apps/cli/src/phalanx/team/spawn.py`  
**Lines:** 25–113

- Builds task file, DB record, etc.
- Calls `process_manager.spawn(..., auto_approve=auto_approve)` at lines 63–74.

### Actual tmux spawn: `ProcessManager.spawn`

**File:** `apps/cli/src/phalanx/process/manager.py`  
**Lines:** 192–279

1. **Lines 211–235:** Create tmux session, set `pipe-pane` to stream to `stream.log`, set env (`PHALANX_TEAM_ID`, `PHALANX_AGENT_ID`).
2. **Lines 247–262:** Build command via `backend.build_start_command()`, insert `backend.auto_approve_flags()` when `auto_approve` is True, then:
   ```python
   cmd_str = shlex.join(cmd_parts)
   pane.send_keys(cmd_str, enter=True, literal=True)
   ```
3. No keystrokes are sent after this.

---

## 2. Where `--auto-approve` Is Handled

| Layer            | File                         | Line(s) | Behavior                                                                 |
|-----------------|------------------------------|---------|----------------------------------------------------------------------------|
| CLI root option | `cli.py`                     | 77      | `--auto-approve` flag, stored in `ctx.obj["auto_approve"]`                |
| create-team     | `cli.py`                     | 201     | `auto_approve = ctx.obj.get("auto_approve", False)`                       |
| create_team     | `team/create.py`             | 81–94, 177–192, 106–119, 204–218 | Passes `auto_approve` to `spawn_agent()` |
| spawn_agent     | `team/spawn.py`              | 72      | Passes `auto_approve` to `process_manager.spawn()`                        |
| ProcessManager  | `process/manager.py`         | 255–261 | If `auto_approve`, inserts `backend.auto_approve_flags()` into command     |
| CursorBackend   | `backends/cursor.py`         | 70–71   | `auto_approve_flags()` returns `["--yolo"]`                               |

`--auto-approve` only affects the **CLI flags** given to the agent binary. It does not inject any post-spawn keystrokes.

---

## 3. Where Cursor TUI Is Launched

**File:** `apps/cli/src/phalanx/process/manager.py`  
**Lines:** 247–263

```python
# Build the TUI command (no --print)
cmd_parts = backend.build_start_command(
    prompt=prompt,
    soul_file=soul_file,
    model=model,
    worktree=worktree,
)

if auto_approve:
    approve_flags = backend.auto_approve_flags()
    for flag in approve_flags:
        if flag not in cmd_parts:
            cmd_parts.insert(1, flag)

cmd_str = shlex.join(cmd_parts)
pane.send_keys(cmd_str, enter=True, literal=True)
```

**Cursor backend:** `backends/cursor.py` lines 24–44

- `build_start_command()` returns something like:  
  `["agent", "--model", "X", "Read and execute instructions from /path/to/task.md"]`
- With `auto_approve`, `--yolo` is inserted at index 1:  
  `["agent", "--yolo", "--model", "X", "Read and execute..."]`

The `agent` binary is Cursor TUI. It is started when this command is sent into the tmux pane via `pane.send_keys()`.

---

## 4. Two Different “Approval” Layers

| Layer            | What it controls                         | Mechanism                          |
|------------------|------------------------------------------|------------------------------------|
| Phalanx / agent  | Message acceptance, tool calls           | `--yolo` flag passed to agent CLI  |
| Cursor TUI       | Shell command allowlist (`cd`, `ls`, …)  | “Run Everything” toggle (Shift+Tab)|

- `--yolo` affects Phalanx/agent-level behavior.
- Cursor TUI’s shell approval is **independent**. “Run Everything” (Shift+Tab) bypasses the allowlist.
- Phalanx never sends Shift+Tab after spawn, so agents start with “Run Everything” off and block on basic commands.

---

## 5. Where BTab Keystroke Should Be Sent

The ProcessManager already sends keystrokes via `send_keys()` (lines 341–378) and uses special keys (e.g. `C-c` at line 518 in `team_monitor.py`).

Recommended fix: add a **post-spawn keystroke** for Cursor when `auto_approve` is True.

### Option A: In `ProcessManager.spawn` (primary location)

**File:** `apps/cli/src/phalanx/process/manager.py`  
**After line 263** (immediately after `pane.send_keys(cmd_str, enter=True, literal=True)`):

```python
pane.send_keys(cmd_str, enter=True, literal=True)

# When auto_approve is used with Cursor, enable "Run Everything" so shell
# commands (cd, ls, etc.) bypass the allowlist. BTab (Shift+Tab) toggles this.
if auto_approve and backend.name() == "cursor":
    time.sleep(5)  # Wait for Cursor TUI to boot and show the prompt
    pane.send_keys("BTab", enter=False)
    logger.debug("Sent BTab to enable Run Everything for %s", agent_id)

agent_proc = AgentProcess(...)
```

Same logic should be added to `spawn_resume` (after line 320) for resumed Cursor agents.

**Note:** `time.sleep(5)` is a heuristic. Cursor startup time can vary. Alternatives:
- Poll `stream.log` for a “ready” pattern.
- Add `backend.run_everything_delay()` / `run_everything_keys()` to the base backend.

### Option B: Backend-driven post-spawn keys (cleaner)

Extend `AgentBackend` in `backends/base.py`:

```python
def run_everything_keys(self) -> list[str]:
    """Keystrokes to enable 'Run Everything' / bypass shell allowlist, if any.
    Called after spawn when auto_approve=True. Default: none."""
    return []

def run_everything_delay(self) -> float:
    """Seconds to wait after sending command before run_everything_keys. Default 0."""
    return 0.0
```

`CursorBackend` override:

```python
def run_everything_keys(self) -> list[str]:
    return ["BTab"]

def run_everything_delay(self) -> float:
    return 5.0
```

Then in `ProcessManager.spawn` (after sending the main command):

```python
if auto_approve:
    delay = backend.run_everything_delay()
    if delay > 0:
        time.sleep(delay)
    for key in backend.run_everything_keys():
        pane.send_keys(key, enter=False)
```

---

## 6. Tmux `send_keys` Syntax

- `C-c` → Ctrl+C  
- `BTab` or `S-Tab` → Shift+Tab  

`libtmux` forwards these to tmux’s `send-keys`. If `BTab` fails, `S-Tab` can be tried.

---

## 7. Files to Change

| File                  | Change                                                                 |
|-----------------------|------------------------------------------------------------------------|
| `process/manager.py`  | After `pane.send_keys(cmd_str, ...)` in `spawn` and `spawn_resume`, add logic to send BTab when `auto_approve` and Cursor backend |
| `backends/base.py`   | Optional: add `run_everything_keys()` and `run_everything_delay()`    |
| `backends/cursor.py` | Optional: implement `run_everything_keys()` and `run_everything_delay()` |

---

## 8. Resume Path

Resume uses the same spawn path:

- `team/orchestrator.py` line 556: `process_manager.spawn_resume()`  
- `team/orchestrator.py` line 571: `process_manager.spawn()`

Both receive `auto_approve`. The BTab logic must be added to **both** `spawn` and `spawn_resume` in `process/manager.py` so resumed agents also get “Run Everything” enabled.
