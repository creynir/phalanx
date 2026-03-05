# Phase 1.5: Task Engine & Headless API (The Bridge)

**Document Version:** 1.0
**Target:** Phalanx Meta-Framework
**Prerequisites:** Phase 1.4 (YAML Parser & MCP Server)

---

## 1. Objectives and Goals

Phase 1.5 bridges the gap between the internal execution engine and the future visual UI. It provides the mechanisms to run workflows entirely from the CLI using declarative tasks, and exposes the filesystem as a database via a REST API.

### 1.1 Primary Objectives

1. **Declarative Task Engine:** Implement a mechanism to define the input `Task` (instruction + context) as a `.yaml` or `.md` file, eliminating the need for Python runner scripts.
2. **CLI Workflow Runner:** Extend the `phalanx` CLI to execute a workflow file against a task file: `phalanx run <workflow.yaml> --task <task.yaml>`.
3. **Headless API (FastAPI):** Build a lightweight REST API that performs CRUD operations on the `custom/` directory (workflows, tasks, souls, blocks). This API will serve as the backend for the Phase 1.6 UI.

### 1.2 Success Criteria

- [ ] A `TaskDef` Pydantic model exists in `phalanx_core.yaml.schema`.
- [ ] A parser can load a `.yaml` file into a `Task` primitive.
- [ ] The `phalanx run` command successfully loads a workflow and a task, executes it, and streams the output to the console.
- [ ] A FastAPI app exists in `apps/cli/src/phalanx/api.py`.
- [ ] FastAPI endpoints `GET /api/workflows` and `POST /api/workflows` can read and write to the `custom/workflows/` directory.
- [ ] A `phalanx server` command starts the FastAPI server on port 8000.

---

## 2. Architecture Decision Record (ADR)

### ADR-1: Filesystem as Database (GitOps)
**Decision:** The FastAPI server will *not* use a relational database for workflow/task storage. It will read and write `.yaml` files directly to the user's `custom/` directory.
**Rationale:** Preserves the GitOps developer experience. Workflows remain version-controllable and easily shareable. The API simply acts as a proxy for the UI to interact with the local filesystem.

### ADR-2: Task Definition Format
**Decision:** Tasks will be defined primarily in YAML, supporting multiline strings for `instruction` and `context`.
**Rationale:** Consistent with Workflow and Soul definitions. Allows easy embedding of complex prompts.

---

## 3. Component Design

### 3.1 Task YAML Schema

```yaml
# custom/tasks/my_task.yaml
version: "1.0"
task:
  id: feature_123
  instruction: |
    Implement the Phase 1.5 specification.
  context: |
    Use FastAPI and Pydantic.
```

### 3.2 CLI Runner (`phalanx run`)

A new command in `apps/cli/src/phalanx/cli.py`:

```bash
phalanx run custom/workflows/my_workflow.yaml --task custom/tasks/my_task.yaml
```

- Loads both YAMLs using the auto-discovery engine.
- Initializes `WorkflowState(current_task=task)`.
- Calls `workflow.run()`.
- Streams `messages` from the state to the console using rich formatting.

### 3.3 FastAPI Server (`apps/cli/src/phalanx/api.py`)

A standard FastAPI application with the following core endpoints:

- `GET /api/workflows` -> Returns a list of all parsed workflows from `custom/workflows/`.
- `POST /api/workflows` -> Accepts a JSON/YAML payload, validates it using `PhalanxWorkflowFile` schema, and writes it to `custom/workflows/{name}.yaml`.
- `GET /api/tasks` -> Returns a list of all parsed tasks.
- `POST /api/tasks` -> Writes a new task YAML.
- `POST /api/workflows/{id}/run` -> Accepts a task ID, spins up an asynchronous background task to execute the workflow, and returns an execution ID (integrates with the existing `StateDB` for tracking runs).