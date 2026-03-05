# Phalanx Phase 1.6 — UI/UX Design Document

## Overview

Phalanx is an Agentic Developer Tool that stores workflows, agent souls, and tasks as YAML files in a GitOps repository. Phase 1.6 introduces a **React/Next.js visual frontend** that lets engineers design, inspect, and run multi-agent workflows without hand-editing YAML. The UI is a first-class citizen: it reads from and writes back to the same `.phalanx/` directory structure, maintaining full GitOps compatibility.

---

## 1. Core Principles

| Principle | Description |
|-----------|-------------|
| **YAML-first** | The canvas is a YAML visualizer/editor, not a separate database. Every drag, rename, or connection writes valid YAML back to disk via the API. |
| **GitOps-compatible** | Changes produce clean diffs. The UI never reformats or reorders YAML arbitrarily. |
| **Progressive disclosure** | Simple workflows look simple. Advanced options (retries, timeouts, memory, tool grants) hide behind an expandable panel. |
| **Agent as a node** | Every agent soul, task, and team is a first-class node type on the canvas. |
| **Run-aware** | The canvas doubles as a live run monitor, showing status, logs, and artifacts inline. |

---

## 2. Page Structure & Layout

```
+------------------------------------------------------------------+
|  Top Bar:  [Phalanx logo]  [Project selector]  [Run >]  [User]  |
+----------+---------------------------------------------------------+
|          |                                                         |
|  Left    |           Canvas (DAG / State Machine)                  |
|  Sidebar |                                                         |
|  (Node   |   +-------+   +-------+   +-------+                   |
|  Library)|   | Soul  |-->| Task  |-->| Task  |                   |
|          |   +-------+   +-------+   +-------+                   |
|  Souls   |         |                      |                       |
|  Tasks   |         v                      v                       |
|  Teams   |   +----------+          +----------+                  |
|  Tools   |   |  Branch  |          |  Branch  |                  |
|          |   +----------+          +----------+                  |
+----------+---------------------------------------------------------+
|  Bottom Bar:  Run log / Feed stream (collapsible)                 |
+-------------------------------------------------------------------+
                                          ^
                                  Right panel slides
                                  in on node select
```

### 2.1 Top Bar
- **Project selector** — dropdown that switches the active `.phalanx/` root (supports multiple repos mounted via config).
- **Run > button** — triggers `phalanx run` for the selected workflow; turns into a live status badge while running.
- **Diff / Commit button** — shows a modal with the YAML diff of unsaved changes and a one-click commit to git.

### 2.2 Left Sidebar — Node Library
A searchable, drag-ready palette organised into four tabs:

| Tab | Contents |
|-----|----------|
| **Souls** | Agent soul files from `.phalanx/souls/`. Shows name + model badge. |
| **Tasks** | Reusable task definitions from `.phalanx/tasks/`. |
| **Teams** | Team templates from `.phalanx/teams/`. Can be dropped as a sub-graph. |
| **Tools** | MCP tool stubs; drag onto a soul to grant tool access. |

Each item shows a tiny icon, name, and a tooltip with the first line of its YAML description. Dragging a node from the palette creates a new YAML entry and drops a new node on the canvas.

### 2.3 Canvas
The central workspace. Built on **React Flow** (or equivalent) with a custom node renderer.

**Node types:**

| Type | Shape | Colour | Description |
|------|-------|--------|-------------|
| `soul` | Rounded rect | Indigo | Agent identity + model config |
| `task` | Rectangle | Blue | A single task with prompt |
| `team` | Thick border rect | Teal | A team sub-graph (collapsible) |
| `branch` | Diamond | Amber | Conditional edge (eval expression) |
| `tool` | Pill | Green | MCP tool grant attached to a soul |
| `artifact` | Document icon | Grey | Output/input artifact node |

**Canvas interactions:**
- **Drag from palette** -> drops node, creates YAML stub.
- **Drag edge** between ports -> creates a dependency/sequence edge; writes `depends_on` or `next` in YAML.
- **Double-click node** -> opens the inline prompt editor (see Section 4).
- **Right-click node** -> context menu: Rename / Duplicate / Delete / View YAML / Run from here.
- **Ctrl+Z / Cmd+Z** -> undo last canvas action (backed by YAML versioning via git).
- **Mini-map** in bottom-right corner for large graphs.
- **Auto-layout button** — runs Dagre/ELK layout algorithm on demand.

### 2.4 Right Panel — Node Inspector
Slides in when a node is selected. Consists of three collapsible sections:

1. **Identity** — name, type badge, file path (clickable -> opens raw YAML in editor pane).
2. **Config** — form fields generated from the node's YAML schema (model, temperature, max_tokens, retries, timeout).
3. **Prompt / Task Body** — the rich prompt editor (see Section 4).

### 2.5 Bottom Bar — Run Log and Feed
Collapsible panel showing:
- Live `phalanx feed` stream (auto-refreshed every 2 seconds).
- Structured log lines with agent ID, timestamp, status badge.
- Clickable log lines jump to the relevant node on the canvas and highlight it.
- "View Artifact" button per completed agent opens the artifact in a side modal.

---

## 3. Workflow Canvas UX — DAG vs State Machine

Phalanx workflows can be either a **directed acyclic graph** (pipeline) or a **state machine** (with cycles/branches). The UI handles both with the same canvas but different edge semantics.

### 3.1 DAG Mode (default)
- Edges represent data/control flow: top-to-bottom or left-to-right.
- Each node runs after all its `depends_on` nodes succeed.
- Branch diamonds select which outgoing edge to follow based on an expression evaluated at runtime.
- Layout: auto-ranks nodes by depth; user can override positions.

### 3.2 State Machine Mode
- Enabled via a toggle in the workflow settings panel.
- Nodes represent states; edges represent transitions with optional guard conditions.
- Cycles are allowed and rendered with curved edges.
- A special Start node and End node are auto-added.
- Hovering an edge shows the transition guard expression inline.

### 3.3 Switching Modes
A "Workflow Type" toggle in the top bar switches the visual rendering and edge validation rules without altering the YAML structure (since both modes use the same underlying YAML schema).

---

## 4. Prompt & Task Editing UX

The heart of Phalanx authoring is writing prompts and task instructions. The editor must be powerful yet distraction-free.

### 4.1 Inline Prompt Editor
Opened by double-clicking a `task` or `soul` node. Renders inside the Right Panel's Prompt section:

- **Monaco Editor** (VS Code engine) embedded in the panel.
- Syntax: plain text with Jinja2-style variable interpolation highlighted (`{{ agent.name }}`, `{{ artifacts.plan }}`).
- Autocomplete for available context variables (team feed, artifact names, soul names).
- **Token counter** badge (estimated tokens for the selected model) updates live.
- **Split-view toggle**: show rendered prompt on the right (variables resolved from last run's context).
- Height expands to fill the panel; ESC collapses back to summary.

### 4.2 Full-Screen Prompt Editor
Triggered via the Expand icon on the inline editor:
- Takes over the canvas area.
- Two-pane layout: raw YAML on the left, rich Markdown preview on the right.
- Breadcrumb at top: `workflow > team > agent > task > prompt`.
- "Save & Close" writes the YAML and returns to canvas.

### 4.3 Soul Editor
Souls have a more structured edit form (not a free-text prompt):

| Field | UI Control |
|-------|------------|
| `name` | Text input |
| `model` | Dropdown (gpt-4o, claude-3-5-sonnet, etc.) |
| `temperature` | Slider 0-2 |
| `system_prompt` | Monaco editor (collapsible) |
| `tools` | Tag picker (MCP tool stubs) |
| `memory` | Toggle + memory backend selector |
| `max_tokens` | Number input |

### 4.4 Task Form

| Field | UI Control |
|-------|------------|
| `id` | Text input (slug, auto-generated) |
| `title` | Text input |
| `description` | Short textarea |
| `prompt` | Monaco editor (see Section 4.1) |
| `depends_on` | Multi-select from other task IDs in scope |
| `output_artifact` | Text input (artifact key) |
| `agent` | Dropdown (souls in scope) |
| `retries` | Number input |
| `timeout` | Duration input (e.g. `5m`) |

---

## 5. Navigation & Information Architecture

```
/ (Dashboard)
+-- /workflows          -- list of all workflow YAML files
|   +-- /workflows/:id  -- canvas view for a specific workflow
+-- /souls              -- gallery of agent soul files
|   +-- /souls/:id      -- soul editor
+-- /teams              -- team definitions
|   +-- /teams/:id      -- team canvas (same component as workflow canvas)
+-- /runs               -- run history + live runs
|   +-- /runs/:id       -- run detail (gantt + live log)
+-- /settings           -- repo config, model credentials, MCP servers
```

### 5.1 Dashboard
- **Recent runs** widget: last 10 runs with status badges.
- **Quick actions**: New Workflow, New Soul, New Team.
- **Feed widget**: latest 20 team feed messages across all teams.
- **Health summary**: any agents in error state, any YAML validation failures.

### 5.2 Workflow List
- Card grid view. Each card shows: workflow name, last run status, number of agents, last modified.
- Filter by status, team, or label.
- "Import from YAML" button for pasting raw YAML.

### 5.3 Run History
- Table view with columns: run ID, workflow, status, duration, triggered by, artifacts produced.
- Clicking a run loads the Run Detail page:
  - Gantt chart of agent execution timelines.
  - Canvas with live status overlays on each node (pending / running / done / error).
  - Per-agent expandable log accordion.
  - Artifact viewer: raw JSON/Markdown artifact content with copy button.

---

## 6. Key UX Patterns

### 6.1 Optimistic UI + YAML Sync
Every canvas edit is applied optimistically in the UI and queued to write to disk. A subtle "Unsaved changes" badge appears in the top bar. Auto-save fires after 1 second of inactivity. Manual save via Cmd+S.

### 6.2 Validation Feedback
- YAML schema validation runs client-side on every edit.
- Invalid fields show a red border + tooltip with the schema error.
- Nodes with validation errors show a red dot badge on the canvas.
- A global Validate button runs `phalanx validate` server-side and surfaces any cross-file errors.

### 6.3 Contextual Help
- Every form field has an info icon that expands a short description pulled from the YAML schema description field.
- A Docs panel can be pinned to the right of the inspector, showing rendered Phalanx documentation for the hovered concept.

### 6.4 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Cmd+S | Save current file |
| Cmd+Z | Undo |
| Cmd+Shift+Z | Redo |
| Cmd+K | Command palette (fuzzy search all nodes, files, runs) |
| Space+Drag | Pan canvas |
| Scroll | Zoom canvas |
| F | Fit graph to viewport |
| Del | Delete selected node(s) |
| Esc | Close panel / deselect |

### 6.5 Command Palette
Cmd+K opens a Spotlight-style palette:
- Search souls, tasks, teams, runs by name.
- Run commands: "Run workflow X", "New soul", "Open settings".
- Recent files section.

### 6.6 Multi-select & Bulk Operations
- Shift+click or drag-select multiple nodes.
- Bulk delete, bulk move, or extract selection into a new team (creates a sub-graph YAML file).

---

## 7. Visual Design System

### 7.1 Colour Palette

| Token | Value | Usage |
|-------|-------|-------|
| primary | #6366f1 (indigo) | Soul nodes, active states |
| task | #3b82f6 (blue) | Task nodes |
| team | #14b8a6 (teal) | Team containers |
| branch | #f59e0b (amber) | Branch nodes |
| success | #22c55e | Run success |
| error | #ef4444 | Run error / validation |
| surface | #0f172a | Canvas background (dark) |
| panel | #1e293b | Sidebar / panel bg |
| border | #334155 | Node borders |

### 7.2 Typography
- Font: Inter (UI) + JetBrains Mono (code/YAML)
- Node labels: 13px medium
- Panel headers: 14px semibold
- Monospace: 13px (prompt editor, YAML view)

### 7.3 Dark Mode First
The canvas and panels default to dark mode (developer tool conventions). A light mode toggle is available in settings.

### 7.4 Node Anatomy

```
+-----------------------------+
|  * soul   [indigo badge]    |  <- type + status dot
|  my-planner-agent           |  <- name (editable inline)
|  gpt-4o  3 tasks            |  <- metadata line
+-----------------------------+
      o (output port)           <- drag to connect
```

---

## 8. Technical Stack Recommendations

| Concern | Recommendation |
|---------|----------------|
| Framework | Next.js 14 (App Router) |
| Canvas | React Flow v11 |
| State | Zustand (canvas state) + React Query (server state) |
| Editor | Monaco Editor (via @monaco-editor/react) |
| Styling | Tailwind CSS + shadcn/ui |
| YAML | js-yaml for parse/stringify |
| Schema validation | Zod (runtime) + JSON Schema from YAML spec |
| Git integration | isomorphic-git or server-side simple-git |
| WebSocket / SSE | For live run feed streaming |
| Icons | Lucide React |

---

## 9. Phase 1.6 Scope Boundaries

### In Scope
- Canvas for DAG and State Machine workflows
- Left sidebar node library (Souls, Tasks, Teams, Tools)
- Right panel node inspector with prompt editor
- Run history page with Gantt + live log
- Dashboard with feed widget
- YAML read/write sync
- Keyboard shortcuts + command palette
- Dark mode

### Out of Scope (deferred)
- Real-time collaboration (multiplayer canvas)
- Visual debugger / step-through execution
- Mobile/tablet layout
- Plugin marketplace
- AI-assisted prompt suggestions

---

## 10. Feel & Interaction Philosophy

Phalanx should feel like **Linear meets Figma meets VS Code**:
- **Linear**: clean, fast, keyboard-driven, no fluff.
- **Figma**: the canvas is the primary surface; everything else orbits it.
- **VS Code**: first-class code/text editing, extensible, respects the developer.

The tool should reward power users with depth (full YAML access, bulk operations, CLI parity) while being approachable to someone who has never edited a YAML workflow before (drag a soul, connect a task, hit Run).

Every action should feel **immediate and reversible**. The undo stack and git diff are the safety net — users should feel free to experiment.