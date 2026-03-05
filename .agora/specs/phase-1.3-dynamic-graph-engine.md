# Phase 1.3: Dynamic Graph Engine — Architectural Deep Dive

**Document Version:** 1.0  
**Target:** Phalanx Meta-Framework  
**Prerequisites:** Phase 1.2e (Workflow/Step/Block separation)

---

## 1. Objectives and Goals

### 1.1 Primary Objectives

Phase 1.3 extends the Phalanx workflow engine from **sequential, static execution** to a **dynamic graph** capable of:

1. **Multi-path branching** — Decisions made at runtime (e.g., by `RouterBlock`) determine which Step executes next, instead of following a fixed linear transition.
2. **On-the-fly graph mutation** — When `EngineeringManagerBlock` (or equivalent) encounters unknown/failure scenarios, it generates new Steps; the engine injects these into the active Workflow and continues execution.

### 1.2 Success Criteria

| Criterion | Description |
|-----------|-------------|
| **DR-1** | Workflow runner evaluates `metadata["router_decision"]` (or block-scoped equivalent) after RouterBlock/Step execution and selects next Step from a multi-outcome transition map. |
| **DR-2** | Workflow runner detects `metadata["{block_id}_new_steps"]` (or canonical key) after EngineeringManagerBlock execution and dynamically injects new Steps into the active DAG before continuing. |
| **DR-3** | Backward compatibility: Workflows with only linear transitions behave identically to Phase 1.2e. |
| **DR-4** | Acyclic invariant preserved: Dynamic injection does not introduce cycles (or is explicitly bounded). |

### 1.3 Out-of-Scope (Deferred)

- **Parallel fan-out at the Workflow level** — `FanOutBlock` already handles intra-block parallelism; Workflow-level parallelism (multiple concurrent Steps) is Phase 2+.
- **Exception-based transitions** — Routing on caught exceptions (e.g., `on_error → recovery_step`) is Phase 2.
- **Human-in-the-loop gates** — Pause-and-resume with human approval is Phase 2.

---

## 2. Architecture Decision Record (ADR): Graph Engine

### ADR-1: Workflow as Mutable Graph at Runtime

**Status:** Accepted  
**Context:** Phase 1.2e establishes Workflow as the DAG, Step as the orchestration wrapper, Block as the execution engine. The graph is currently immutable at runtime.  
**Decision:** The Workflow graph is **mutable at runtime** for dynamic injection only. Static definition remains the primary API; mutation is an internal engine concern triggered by block output.  
**Consequences:**  
- Engine maintains a runtime graph representation (nodes = Steps, edges = transitions).  
- Validation runs at definition time for static structure; post-injection validation is lightweight (e.g., no new cycles).

---

### ADR-2: Routing Metadata Convention

**Status:** Accepted  
**Context:** `RouterBlock` stores decision in `metadata["{block_id}_decision"]`. Engine needs a consistent way to resolve "which Step next?"  
**Decision:**  
- **Primary key:** `metadata["router_decision"]` — Canonical key for the *last* router in the current path. Engine populates this after any RouterBlock/Step execution.  
- **Fallback:** For Step-scoped routing, `metadata["{step_id}_decision"]` remains available; engine resolves via Step → Block mapping.  
- **Semantics:** `router_decision` is a string (e.g., `"approved"`, `"rejected"`, `"escalate"`). Transition map: `{(from_step_id, decision_value) -> to_step_id}`.

**Consequences:**  
- RouterBlock (or its Step wrapper) may optionally set `metadata["router_decision"]` for engine convenience; otherwise engine copies `metadata["{block_id}_decision"]` → `router_decision` after execution.  
- Multi-router workflows: Only the *immediate* router’s decision matters for the next transition; earlier routers’ decisions remain in metadata for auditing.

---

### ADR-3: Dynamic Step Injection Contract

**Status:** Accepted  
**Context:** `ReplannerBlock` / `EngineeringManagerBlock` produces `metadata["{block_id}_new_steps"]` as `List[Dict[str, str]]` with `step_id` and `description`.  
**Decision:**  
- **Canonical key:** `metadata["injected_steps"]` — Engine looks for this (or `{block_id}_new_steps`) after Step execution.  
- **Schema:**  
  ```json
  [
    {"step_id": "research_phase", "description": "Gather requirements"},
    {"step_id": "design_phase", "description": "Create architecture"}
  ]
  ```
- **Injection semantics:**  
  - New Steps are **appended** after the current (EngineeringManager) Step.  
  - Each new Step receives a **placeholder Block** (e.g., `LinearBlock` with a Soul that executes `description` as the task instruction) unless a block registry maps `step_id` → concrete Block.  
  - Transitions: `current_step → injected_step_0 → injected_step_1 → … → next_static_step` (if any).  
  - Injection is **one-shot per Step** — the same Step does not inject again in the same run to avoid unbounded growth.

**Consequences:**  
- EngineeringManagerBlock must emit structured JSON; the engine parses and validates before injection.  
- Placeholder Blocks can be replaced by a **Block registry** (see Section 4) for custom implementations.

---

### ADR-4: Step vs Block in the Engine

**Status:** Accepted  
**Context:** Phase 1.2e defines Step as the orchestration wrapper (pre_hooks, post_hooks) around a Block.  
**Decision:** The Workflow engine operates on **Steps**, not Blocks. Each Step wraps exactly one Block. The graph nodes are Step IDs; Block execution is encapsulated inside `Step.execute()`.  
**Consequences:**  
- `add_step(step: Step)` and `add_transition(from_step_id, to_step_id)` (or multi-outcome variant).  
- RouterBlock’s decision is produced by the Block; the Step runs pre_hook → block → post_hook; the engine inspects `state.metadata` after `Step.execute()`.

---

### ADR-5: Validation of Dynamic Graphs

**Status:** Accepted  
**Decision:**  
- **Static validation:** At Workflow build time, validate entry exists, all transitions reference valid Steps, no cycles.  
- **Post-injection validation:** After injection, run lightweight cycle check from entry; if cycle detected, **reject injection** and escalate (e.g., emit warning, continue to terminal or human escalation).  
- **Bounded injection:** Optional config `max_injected_steps` (e.g., 20) to prevent runaway growth.

---

## 3. Component-Level Design

### 3.1 Graph Model

```
┌─────────────────────────────────────────────────────────────────┐
│                         Workflow (DAG)                           │
│  - name: str                                                     │
│  - steps: Dict[str, Step]    # step_id → Step                    │
│  - transitions: Dict[str, str | Dict[str, str]]                  │
│    # Linear: step_id → next_step_id                              │
│    # Conditional: step_id → { "approved" -> X, "rejected" -> Y } │
│  - entry_step_id: str                                            │
│  - runtime_graph: MutableGraph (internal)                         │
└─────────────────────────────────────────────────────────────────┘
```

**Transition representation (options):**

- **Option A — Uniform:** `transitions: Dict[str, Union[str, Dict[str, str]]]`  
  - `"step_a" -> "step_b"` (linear)  
  - `"router_step" -> {"approved": "step_yes", "rejected": "step_no"}` (conditional)
- **Option B — Separate:** `linear_transitions: Dict[str, str]` and `conditional_transitions: Dict[str, Dict[str, str]]`.  
  - Lookup: Check conditional first; if key missing, use linear.

**Recommendation:** Option A for simplicity; single lookup method.

---

### 3.2 Workflow Runner Algorithm

```
Algorithm: Workflow.run(initial_state)
─────────────────────────────────────
1. Validate static graph (entry, refs, cycles)
2. current_step_id := entry_step_id
3. state := initial_state
4. WHILE current_step_id != None:
   a. step := steps[current_step_id]
   b. state := await step.execute(state)
   c. ─── ROUTING ───
      IF step has conditional transitions:
         decision := state.metadata.get("router_decision") or state.metadata.get(f"{step.block.block_id}_decision")
         next_step_id := transitions[current_step_id].get(decision) or transitions[current_step_id].get("default")
      ELSE:
         next_step_id := transitions.get(current_step_id)
   d. ─── INJECTION ───
      new_steps_raw := state.metadata.get("injected_steps") or state.metadata.get(f"{step.block.block_id}_new_steps")
      IF new_steps_raw is a non-empty list:
         injected := parse_and_validate(new_steps_raw)
         inject_steps_after_current(injected, current_step_id)
         next_step_id := injected[0]["step_id"]  # First injected step runs next
   e. current_step_id := next_step_id
5. RETURN state
```

**Details:**

- **Router decision resolution:** Prefer `router_decision`; fallback to `{block_id}_decision` for backward compatibility.
- **Default branch:** `conditional_transitions["default"]` allows a catch-all when decision does not match any key.
- **Injection override:** If both routing and injection occur, **injection takes precedence** — the next Step is the first injected Step.

---

### 3.3 Dependency Evaluation

**Current model (Phase 1.2e):** Steps are ordered by explicit transitions. There are no explicit "depends_on" declarations; the graph structure implies dependencies.

**Phase 1.3:**  
- Dependencies are **implicit** in the transition graph. A Step `B` depends on Step `A` iff there is a path from entry to `B` that goes through `A`.  
- **Conditional branches:** A Step may have multiple predecessors (e.g., `approved_path` and `rejected_path` merge later). The engine does not require explicit join semantics for Phase 1.3 — each path is linear until the next decision or terminal.  
- **Fan-out (future):** Explicit dependency DAG (e.g., `Step C depends_on [A, B]`) is Phase 2.

---

### 3.4 Conditional Branching

**API for conditional transitions:**

```python
# Linear
workflow.add_transition("research", "review")

# Conditional (RouterBlock)
workflow.add_conditional_transition(
    "router_step",
    {"approved": "proceed_step", "rejected": "reject_step", "default": "reject_step"}
)
```

**Engine behavior:**

1. After `router_step` executes, read `state.metadata["router_decision"]` (or `router_step_decision`).
2. Look up `transitions["router_step"][decision]`.
3. If missing, use `transitions["router_step"]["default"]` if present.
4. If still missing, treat as terminal (no next Step) or raise `WorkflowError` (configurable).

---

### 3.5 Dynamic Step Injection

**Injection flow:**

1. **Detection:** After `engineering_manager_step.execute(state)`, engine checks `metadata["injected_steps"]` or `metadata["{block_id}_new_steps"]`.
2. **Parse:** Expect `List[Dict]` with `step_id` and `description`.
3. **Resolve Block:** For each item, lookup `block_registry.get(step_id)` or use `PlaceholderBlock(step_id, description)`.
4. **Create Steps:** Wrap each Block in a Step (with optional pre/post hooks from config).
5. **Splice:** Insert Steps after current in the runtime graph; set transition `current → injected_0 → injected_1 → …` and `injected_last → previous_next` (or terminal).

**PlaceholderBlock behavior:**

- Executes a `Task` with `instruction=description`, using a configurable default Soul (e.g., `generalist_soul`).
- Allows workflows to add Steps without pre-defining Blocks; custom Blocks can be registered later.

---

## 4. Developer User Experience

### 4.1 Creating and Hooking Up a Custom Block

**Approach:** **Open repo + optional registry.** No mandatory plugin system; developers can:

1. **Direct use:** Instantiate `Step(my_custom_block)` and add to Workflow. No registration required.
2. **Registry (optional):** Register Blocks by ID for use in dynamic injection and/or higher-level DSLs.

**Custom Block implementation:**

```python
from phalanx_core.blocks.base import BaseBlock
from phalanx_core.state import WorkflowState

class MyCustomBlock(BaseBlock):
    def __init__(self, block_id: str, config: dict):
        super().__init__(block_id)
        self.config = config

    async def execute(self, state: WorkflowState) -> WorkflowState:
        # Read from state, produce output
        result = await self._do_work(state)
        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: result},
                "messages": state.messages + [{"role": "system", "content": f"[{self.block_id}] Done"}],
            }
        )
```

**Wrapping in a Step:**

```python
from phalanx_core.primitives import Step

my_block = MyCustomBlock("my_block", {"option": "value"})
step = Step(my_block, pre_hook=log_start, post_hook=log_end)
workflow.add_step(step)
workflow.add_transition("previous_step", "my_block")
```

---

### 4.2 Block Registry (Internal vs External)

**Design:**

| Layer | Scope | Mechanism |
|-------|--------|-----------|
| **Internal blocks** | `phalanx_core.blocks` | Built-in: `LinearBlock`, `RouterBlock`, `MessageBusBlock`, `EngineeringManagerBlock`, etc. |
| **External blocks** | User / third-party | Optional `BlockRegistry` for dynamic resolution by `step_id` |

**BlockRegistry API (proposed):**

```python
from phalanx_core.blocks.registry import BlockRegistry

registry = BlockRegistry()

# Register internal blocks (done by framework)
registry.register("linear", LinearBlock)
registry.register("router", RouterBlock)
# ...

# User registers custom block for injection
def make_research_block(step_id: str, config: dict) -> BaseBlock:
    return MyResearchBlock(step_id, config)

registry.register("research_phase", make_research_block)
```

**When injection occurs:**

- For each `{"step_id": "research_phase", "description": "..."}`, engine calls `registry.get("research_phase")(step_id, {"description": "..."})` if present.
- Otherwise, use `PlaceholderBlock(step_id, description)`.

**Recommendation:** Keep registry **optional**. Workflows that do not use dynamic injection or higher-level DSLs need not use it.

---

### 4.3 Registering Custom Hooks for Steps

**Current model (Phase 1.2e):** Step accepts `pre_hook` and `post_hook` as `Callable[[WorkflowState], WorkflowState]` at construction time.

**Phase 1.3 options:**

1. **Constructor only (unchanged):** Pass hooks when creating Step. No registry.
2. **Hook registry by step_id:**  
   ```python
   workflow.register_step_hooks("research_step", pre_hook=f, post_hook=g)
   ```
   When Workflow builds the execution plan, it attaches hooks from the registry to the Step. Useful for declarative config.
3. **Global hook middleware:** A list of `(predicate, hook)` applied to every Step where predicate matches. More flexible but complex.

**Recommendation:**  
- **Phase 1.3:** Retain constructor-based hooks only. Keep the API simple.  
- **Future:** Add `workflow.register_step_hooks(step_id, ...)` as an optional convenience for config-driven workflows.

**Example (current):**

```python
def pre_log(state: WorkflowState) -> WorkflowState:
    return state.model_copy(update={"metadata": {**state.metadata, "pre_ran": True}})

step = Step(router_block, pre_hook=pre_log, post_hook=None)
workflow.add_step(step)
```

---

### 4.4 End-to-End Developer Flow

```
1. Define Blocks (built-in or custom)
   └─ Custom: subclass BaseBlock, implement execute()

2. Wrap in Steps (with optional hooks)
   └─ Step(block, pre_hook=..., post_hook=...)

3. Build Workflow
   └─ workflow.add_step(step)
   └─ workflow.add_transition(from_id, to_id)
   └─ workflow.add_conditional_transition(router_id, {decision: target})

4. (Optional) Register Blocks for dynamic injection
   └─ registry.register(step_id, block_factory)

5. Run
   └─ final_state = await workflow.run(initial_state)
```

---

## 5. Implementation Phases (Suggested)

| Phase | Deliverable |
|-------|-------------|
| **1.3a** | Extend Workflow transition model to support `Dict[str, str]` for conditional routing. Implement routing logic in `run()`. |
| **1.3b** | Implement dynamic injection: detect `injected_steps` / `_new_steps`, parse, splice into runtime graph. Add `PlaceholderBlock`. |
| **1.3c** | Add optional `BlockRegistry` and integrate with injection. |
| **1.3d** | Align `router_decision` convention; ensure RouterBlock/Step sets canonical key. Update docs and tests. |

---

## 6. Summary

Phase 1.3 transforms the Phalanx workflow engine from a static, linear pipeline into a **dynamic graph** that supports:

- **Conditional branching** driven by `metadata["router_decision"]` and multi-outcome transitions.
- **Runtime graph mutation** when `EngineeringManagerBlock` (or equivalent) emits `injected_steps`, with placeholder Blocks for unknown step_ids and an optional registry for custom Blocks.
- **Backward compatibility** for linear workflows.
- **Simple developer UX** — open repo, direct Step/Block usage, optional registry and hook registration for advanced cases.

The design keeps the Phase 1.2e separation (Workflow = DAG, Step = orchestration, Block = execution) and extends it with routing and injection semantics that are explicit, testable, and incremental.
