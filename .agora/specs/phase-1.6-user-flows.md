# Phalanx Phase 1.6 — Core User Flows

This document details the step-by-step interactions for the primary user flows in the Phase 1.6 visual UI, based on the UI/UX design specification.

---

## Flow 1: Creating a new workflow from scratch, adding an agent, and writing a prompt

**Goal:** A user starts with a blank canvas and builds a simple 1-agent workflow.

1. **Start:** User navigates to the Dashboard (`/`) and clicks "New Workflow".
2. **Initialise:** The UI transitions to the Canvas view (`/workflows/new`). An empty DAG canvas is displayed.
   - *Behind the scenes:* A new, empty YAML file is stubbed in memory.
3. **Add Agent Soul:** User opens the Left Sidebar (Node Library) to the "Souls" tab. They drag a predefined "Researcher" soul onto the canvas.
   - *Result:* A blue `soul` node appears. The "Unsaved changes" badge appears in the top bar.
   - *Behind the scenes:* The YAML stub is updated to include this soul reference.
4. **Add Task:** User drags a "Task" node from the "Tasks" tab onto the canvas, placing it below the Soul node.
5. **Connect:** User drags a connection line from the output port of the Soul node to the input port of the Task node.
   - *Result:* An edge is drawn. 
   - *Behind the scenes:* The Task YAML is updated with a `depends_on` or `agent` mapping linking it to the Soul.
6. **Edit Prompt:** User double-clicks the Task node. 
   - *Result:* The Full-Screen Prompt Editor overlays the canvas.
7. **Write Prompt:** The user types instructions into the Monaco editor. They type `{{` to trigger autocomplete and select an input variable (e.g., `{{ input.query }}`).
8. **Save:** The user clicks "Save & Close".
   - *Result:* The editor closes, returning to the canvas. The UI auto-saves the file to disk (or the user presses Cmd+S).

---

## Flow 2: Running a workflow and debugging a failure

**Goal:** Execute the workflow, see it fail, identify the issue, and prepare to fix it.

1. **Trigger Run:** With the workflow open on the canvas, the user clicks the "Run >" button in the Top Bar.
2. **Transition to Live Mode:** The canvas switches to read-only "Live Mode". The Top Bar shows a pulsing "Running" badge.
3. **Execution Visualization:** 
   - As the engine executes, nodes light up. 
   - The first node turns a pulsing blue ("Running"). 
   - The Bottom Panel (Run Log / Feed) auto-expands (or user presses Cmd+J), streaming log lines.
4. **Failure Event:** A node fails (e.g., LLM context limit exceeded).
   - *Result:* The node turns red with an error icon. The run halts. The Top Bar badge changes to "Failed".
5. **Debug - Log Inspection:** The user looks at the Bottom Panel. The error is highlighted in red.
6. **Debug - State Inspection:** The user clicks the failed node on the canvas. The Right Inspector slides in.
   - The "Properties" and "Prompt" tabs show the configuration at the time of failure.
   - The "History" or a new "Error Details" tab shows the specific stack trace or LLM error message.
7. **Return to Edit:** The user clicks the "Live/Edit toggle" in the Top Bar to switch back to Edit Mode to fix the prompt or configuration (e.g., increasing `max_tokens` in the Properties panel).

---

## Flow 3: Switching between DAG and State Machine views

**Goal:** Change how a workflow is visually represented and structured.

1. **Current State:** User is viewing a workflow in the default DAG (Directed Acyclic Graph) mode. Edges flow strictly top-to-bottom.
2. **Locate Toggle:** User looks at the Top Bar (or workflow settings in the Right Inspector) and locates the "Workflow Type" toggle.
3. **Switch to State Machine:** User clicks the toggle to "State Machine".
4. **Visual Transformation:** 
   - The layout algorithm re-runs. 
   - Nodes might rearrange to better represent states rather than a strict pipeline.
   - Edges change from straight/angled lines to curved lines, visually allowing for cycles (loops).
   - "Start" and "End" virtual nodes might automatically appear to anchor the state machine.
5. **Interaction Change:** 
   - The user can now drag an edge from a downstream node back to an upstream node (creating a cycle), which is permitted in State Machine mode but would have been blocked/warned in DAG mode.
   - *Behind the scenes:* The UI updates the underlying YAML structure to use state machine semantics (e.g., `transitions` rather than simple `depends_on`).

---

## Flow 4: Saving changes to Git

**Goal:** Commit the visual changes back to the GitOps repository.

1. **Identify Dirty State:** The user finishes editing. The Top Bar shows a "Dirty" or "Uncommitted Changes" indicator next to the Branch selector.
2. **Open Diff/Commit Modal:** The user clicks the "Commit" button in the Top Bar.
3. **Review Diff:** A modal opens. It shows a split-pane view:
   - Left pane: The previous YAML state (from git HEAD).
   - Right pane: The current unsaved YAML state.
   - The user verifies that their visual canvas changes resulted in the expected YAML changes (e.g., a new block was added).
4. **Write Message:** The user types a commit message in the provided text input (e.g., "Add researcher agent and initial prompt").
5. **Commit:** The user clicks the "Commit to branch" button.
   - *Result:* The UI performs a `git commit` via the backend API.
   - The modal closes, a success toast appears, and the "Dirty" indicator in the Top Bar disappears.