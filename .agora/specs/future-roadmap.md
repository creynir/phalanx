# Future Roadmap & Spec

## Phase 1.1: Core Primitives (Completed)
- `Soul`: Definition of agent persona, system prompt, tool access.
- `Task`: Definition of instruction and context.
- `LiteLLMClient`: Unified LLM access layer.
- `Runner`: Basic execution of Tasks by Souls.

## Phase 1.2: The Blueprint Engine (Completed)
### 1.2a & 1.2b: Orchestration Core
- `Workflow` (DAG) and `Step` definitions.
- `BaseBlock` execution engine.
- `LinearBlock` and `FanOutBlock`.

### 1.2d: Advanced Blocks & Swarms
- `MessageBusBlock` for multi-agent (N-Souls) round-robin/debate.
- Adaptive control blocks (`TeamLeadBlock`, `EngineeringManagerBlock`, `RouterBlock`).
- `RetryBlock` for LLM failure recovery.

### 1.2e: Architecture Simplification
- Clear separation: `Workflow` (graph), `Step` (orchestration wrapper with hooks), `Block` (execution logic).
- Terminology aligned (`Blueprint` -> `Workflow`, `Skill` removed, `Advisor` -> `TeamLead`, etc.).

---

## Phase 1.3: Dynamic Graph Engine (Completed)
- **Conditional Branching:** Native pathing based on `router_decision` metadata.
- **Dynamic Step Injection:** On-the-fly DAG mutation by `EngineeringManagerBlock`.
- **PlaceholderBlock:** Fallback execution for injected, undefined steps.
- **BlockRegistry:** Optional internal/external block registration.

---

## Phase 1.4: API & Extensibility Layer (Completed)
- **Phalanx API:** FastAPI application wrapping `phalanx-core`.
- **Auto-Discovery:** Scanning `custom/` directories to dynamically load `BaseBlock` implementations.
- **MCP Server:** Expose Phalanx workflows via the Model Context Protocol, allowing external AIs (Cursor, Claude Desktop) to invoke Phalanx pipelines.

---

## Phase 1.5: Task Engine & Headless API (Completed)
- **Task YAML Parser:** Define initial tasks, contexts, and specs declaratively (`.yaml` or `.md`) to completely eliminate the need for python runner scripts.
- **CLI Workflow Runner:** `phalanx run custom/workflows/landing_page.yaml --task custom/tasks/build_saas_page.yaml`.
- **FastAPI Server (Headless):** Expose endpoints (`/api/workflows`, `/api/tasks`) to read/write YAML files from disk. Treats the filesystem as the primary database.

---

## Phase 1.6: The UI & Visual Builder
- **Next.js GUI:** Visual node-based builder for Workflows.
- **Workflow-as-a-Node (HSM):** Introduce `WorkflowBlock` to allow Workflows to nest inside other Workflows, turning the DAG into a Hierarchical State Machine.
- **Execution Monitoring:** Real-time state visualization.
- **Human-in-the-Loop (HITL) & Runtime Pausing:** Implement `ApprovalBlock` to pause execution.

---

## Phase 2.0: Advanced Control & Memory
- **Auto-Learning Memory:** Vector DB storage of successful error-recovery trajectories (when the system heals itself, it remembers the solution).
- **Cost & Budget Limits:** Execution constraints tied to specific Workflows to prevent runaway loops.

---

## Phase 3.0: Advanced Optimizations
- **Backend Hot-Swapping:** The ability to dynamically change an agent's underlying backend (e.g., from Cursor to Claude Code to a LiteLLM proxy) mid-task.
- **Context Serialization (Enhanced Prompt-Replay):** To support hot-swapping without losing the agent's "chain of thought", the `CheckpointManager` will generate a structured `context_summary`. When swapped to a new backend, the new agent will receive this summary + completed DAG artifacts + remaining tasks.
