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

## Phase 1.3: Dynamic Graph Engine (In Progress)
- **Conditional Branching:** Native pathing based on `router_decision` metadata.
- **Dynamic Step Injection:** On-the-fly DAG mutation by `EngineeringManagerBlock`.
- **PlaceholderBlock:** Fallback execution for injected, undefined steps.
- **BlockRegistry:** Optional internal/external block registration.

---

## Phase 1.4: API & Extensibility Layer
- **Phalanx API:** FastAPI application wrapping `phalanx-core`.
- **Auto-Discovery:** Scanning `custom/` directories to dynamically load `BaseBlock` implementations.
- **MCP Server:** Expose Phalanx workflows via the Model Context Protocol, allowing external AIs (Cursor, Claude Desktop) to invoke Phalanx pipelines.

---

## Phase 1.5: UI / Visual Builder
- **Next.js GUI:** Visual node-based builder for Workflows.
- **Execution Monitoring:** Real-time state visualization.
- **Block Library:** Drag-and-drop standard blocks from `phalanx-core`.

---

## Phase 1.6: Advanced Control & Memory
- **Auto-Learning Memory:** Vector DB storage of successful error-recovery trajectories (when the system heals itself, it remembers the solution).
- **Human-in-the-Loop (HITL):** `ApprovalBlock` that pauses the Workflow state, awaiting manual intervention/confirmation from the CLI or GUI before resuming.
- **Cost & Budget Limits:** Execution constraints tied to specific Workflows to prevent runaway loops.
