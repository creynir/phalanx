# Phase 1.4: API & Extensibility Layer — Architectural Specification

**Document Version:** 1.0  
**Target:** Phalanx Meta-Framework  
**Prerequisites:** Phase 1.2e (Workflow/Step/Block separation), Phase 1.3 (Dynamic Graph Engine)

---

## 1. Objectives and Goals

### 1.1 Primary Objectives

Phase 1.4 exposes the Phalanx execution engine to the outside world through three pillars:

1. **Standard Library & YAML Parser** — Allow non-technical users to define Workflows, Souls, and Tasks in YAML/JSON and parse them into the Python engine without writing code.
2. **Auto-Discovery** — Design an extensible plugin system where users drop Python files containing custom `BaseBlock` subclasses into a `custom/` directory; Phalanx automatically discovers and registers them in `BlockRegistry`.
3. **API & MCP Server** — Expose Phalanx via FastAPI and the Model Context Protocol (MCP) so external AIs (Cursor, Claude Desktop, Langsmith) can discover YAML workflows and trigger them natively as tools.

### 1.2 Success Criteria

| Criterion | Description |
|-----------|--------------|
| **EX-1** | A valid YAML file defining a Workflow (blocks, souls, transitions) parses into a runnable `Workflow` instance without Python code. |
| **EX-2** | A Python file in `custom/` defining a `BaseBlock` subclass is automatically discovered and registered by block_id. |
| **EX-3** | FastAPI exposes endpoints to list workflows, run a workflow with a task, and retrieve workflow schema. |
| **EX-4** | MCP server exposes each loaded workflow as a callable tool; external AI clients can list and invoke workflows via MCP protocol. |
| **EX-5** | Backward compatibility: Programmatic Python API (Workflow, Blocks, Soul, Task) remains fully supported. |

### 1.3 Out-of-Scope (Deferred)

- **Visual GUI** — Drag-and-drop builder is Phase 1.5.
- **Workflow versioning** — Version management and rollback is Phase 2.
- **Authentication/Authorization** — API auth (OAuth, API keys) is Phase 2.
- **Streaming execution status** — WebSocket or SSE for real-time progress is Phase 2.

---

## 2. Architecture Decision Records (ADRs)

### ADR-1: YAML as Primary Declarative Format

**Status:** Accepted  
**Context:** Non-technical users need a way to define workflows without Python. JSON is machine-friendly but verbose; YAML is human-readable and widely used for config (Ansible, Kubernetes, GitHub Actions).  
**Decision:** YAML is the **primary** declarative format. JSON is supported as input (parsed identically after loading). The parser produces Python objects (`Workflow`, `Soul`, `Task`, `BaseBlock`) for execution.  
**Consequences:**  
- Schema validation (JSON Schema or Pydantic) recommended for user-facing errors.  
- Comments preserved only in YAML; JSON users lose inline documentation.  
- File extensions: `.yaml`, `.yml`, `.json` accepted.

---

### ADR-2: Standard Library of Souls and Block Types

**Status:** Accepted  
**Context:** YAML references must resolve to concrete Python types. Built-in blocks (`LinearBlock`, `RouterBlock`, etc.) and common Souls need canonical names.  
**Decision:** Introduce a **Standard Library** module:  
- **Soul Library:** Named souls (e.g., `researcher`, `reviewer`, `engineering_manager`) with predefined `id`, `role`, `system_prompt`. Users override via YAML or extend with custom souls.  
- **Block Type Registry:** String keys (`linear`, `fanout`, `router`, `synthesize`, `debate`, `message_bus`, `retry`, `team_lead`, `engineering_manager`, `placeholder`) map to block classes.  
**Consequences:**  
- Consistent naming across YAML and programmatic APIs.  
- Custom blocks registered via Auto-Discovery get their own string keys (e.g., `my_custom_block`).

---

### ADR-3: Parser Produces Workflow, Not Step-Wrapped Blocks

**Status:** Accepted  
**Context:** Phase 1.2e defines Step as an orchestration wrapper (pre_hook, post_hook) around Block. The current `Workflow` API uses `add_block()` and operates on `BaseBlock` directly.  
**Decision:** The YAML parser produces a `Workflow` with **Blocks** (not Step-wrapped). Step wrapper support is deferred; hooks can be expressed in YAML as optional `pre_hook`/`post_hook` references in a future Phase 1.4 iteration if needed.  
**Consequences:**  
- Simpler parser; one-to-one mapping from YAML block → `BaseBlock`.  
- Hooks remain programmatic-only for Phase 1.4.

---

### ADR-4: Auto-Discovery via Convention over Configuration

**Status:** Accepted  
**Context:** Users want to extend Phalanx without modifying core code. A plugin system must be simple and predictable.  
**Decision:** Use **convention over configuration**:  
- **Directory:** `custom/` (or configurable `PHALANX_CUSTOM_DIR`) relative to workspace or installation.  
- **Discovery:** Scan `custom/**/*.py` for modules; within each, find classes that inherit from `BaseBlock`.  
- **Registration:** Each discovered block class is registered under a canonical ID derived from the class name (e.g., `MyCustomBlock` → `my_custom_block`) or an explicit `block_id` class attribute.  
**Consequences:**  
- No manifest file required; "drop a file" suffices.  
- Security: Discovery runs at load time; execution still respects Workflow sandbox.  
- Cyclic imports: Discovery must avoid loading modules that import phalanx_core before registry is ready.

---

### ADR-5: MCP Tools = Workflow Invocations

**Status:** Accepted  
**Context:** MCP exposes **tools** that AI clients can call. Phalanx workflows are the primary capability to expose.  
**Decision:** Each loaded workflow becomes **one MCP tool**. Tool name: `run_workflow_{workflow_id}` or `phalanx_run_{workflow_id}`. Input schema: `workflow_id`, `task_instruction`, `task_context` (optional). The MCP server executes the workflow with `WorkflowState(current_task=Task(...))` and returns the final state (or a summary) as the tool result.  
**Consequences:**  
- AI clients see Phalanx as a set of tools (e.g., "Run Code Review Pipeline", "Run Research Workflow").  
- Tool discovery is dynamic: workflows loaded from YAML appear automatically.

---

### ADR-6: FastAPI as API Layer, MCP as Separate Server

**Status:** Accepted  
**Context:** FastAPI serves REST/HTTP; MCP uses stdio or HTTP with a different protocol (JSON-RPC style).  
**Decision:**  
- **FastAPI:** Primary HTTP API for listing workflows, running workflows, health checks. Can run standalone or alongside MCP.  
- **MCP Server:** Separate process or embedded within the FastAPI app (same process, different transport). MCP Python SDK (`mcp` package) used for server implementation.  
**Consequences:**  
- Clean separation of concerns; MCP clients (Cursor, Claude) connect via their native MCP transport.  
- Deployment: Single binary/container can run both FastAPI and MCP server.

---

## 3. Component Design

### 3.1 Standard Library & YAML Parser

#### 3.1.1 YAML Document Structure

A Phalanx workflow YAML file has the following top-level structure:

```yaml
# phalanx workflow definition
version: "1.0"

# Optional: global config
config:
  model_name: "gpt-4o"  # Used for PhalanxTeamRunner

# Souls: reusable agent definitions
souls:
  researcher:
    id: researcher_1
    role: Senior Researcher
    system_prompt: |
      You are an expert researcher. Provide concise, structured summaries.
    tools: []  # optional

  reviewer:
    id: reviewer_1
    role: Peer Reviewer
    system_prompt: |
      You are a strict reviewer. Output ONLY "approved" or "rejected".

# Blocks: references souls and block type
blocks:
  initial_research:
    type: linear
    soul_ref: researcher

  review_gate:
    type: router
    soul_ref: reviewer  # RouterBlock with Soul evaluator
    # OR condition_ref: my_custom_check  # For callable (advanced)

  manager_replanner:
    type: engineering_manager
    soul_ref: engineering_manager

  final_publish:
    type: linear
    soul_ref: researcher

# Workflow topology
workflow:
  name: ResearchReviewPipeline
  entry: initial_research
  transitions:
    - from: initial_research
      to: review_gate
    - from: manager_replanner
      to: final_publish
    - from: final_publish
      to: null  # terminal
  conditional_transitions:
    - from: review_gate
      approved: final_publish
      rejected: manager_replanner
      default: manager_replanner
```

**Simplified linear format (alternative):**

```yaml
workflow:
  name: SimplePipeline
  entry: step1
  steps:
    - id: step1
      type: linear
      soul_ref: researcher
    - id: step2
      type: linear
      soul_ref: reviewer
  transitions:
    step1: step2
    step2: null  # terminal
```

#### 3.1.2 Block Type Mapping (Standard Library)

| `type` (YAML) | Block Class | Required Config |
|---------------|-------------|-----------------|
| `linear` | `LinearBlock` | `soul_ref` |
| `fanout` | `FanOutBlock` | `soul_refs` (list) |
| `synthesize` | `SynthesizeBlock` | `input_block_ids`, `soul_ref` |
| `debate` | `DebateBlock` | `soul_a_ref`, `soul_b_ref`, `iterations` |
| `message_bus` | `MessageBusBlock` | `soul_refs`, `iterations` |
| `router` | `RouterBlock` | `soul_ref` (LLM) or `condition_ref` (callable) |
| `retry` | `RetryBlock` | `inner_block_ref`, `max_retries` |
| `team_lead` | `TeamLeadBlock` | `failure_context_keys`, `soul_ref` |
| `engineering_manager` | `EngineeringManagerBlock` | `soul_ref` |
| `placeholder` | `PlaceholderBlock` | (used for injection fallback, rarely in static YAML) |

#### 3.1.3 Block Build Order

Some blocks depend on others:
- **RetryBlock:** `inner_block_ref` must resolve to a block defined earlier. Parser builds blocks in topological order or uses a two-pass approach: first create all blocks, then resolve wrapper refs.
- **SynthesizeBlock:** `input_block_ids` references block IDs; no build-order constraint, only runtime validation that results exist.

**Recommendation:** Two-pass build — (1) create all non-wrapper blocks; (2) create RetryBlock with `inner_block = blocks[inner_block_ref]`.

#### 3.1.4 Parser Algorithm

```
Algorithm: parse_workflow_yaml(path_or_dict) → Workflow
─────────────────────────────────────────────────────
1. Load YAML/JSON into raw dict
2. Parse config: model_name, etc.
3. Parse souls: dict[name → Soul]
4. Instantiate PhalanxTeamRunner(config.model_name)
5. For each block in blocks:
   a. Resolve soul_ref(s) → Soul instance(s)
   b. Look up block type in BlockTypeRegistry
   c. Call block factory(block_id, config, souls_map, runner)
   d. Store block instance
6. Build Workflow:
   a. workflow = Workflow(name)
   b. For each block: workflow.add_block(block)
   c. For each transition: workflow.add_transition(from, to)
   d. For each conditional: workflow.add_conditional_transition(from, map)
   e. workflow.set_entry(entry)
7. Validate: workflow.validate()
8. RETURN workflow
```

#### 3.1.5 Soul Library (Built-in)

Predefined souls for common roles:

| Key | id | role |
|-----|-----|------|
| `researcher` | researcher_1 | Senior Researcher |
| `reviewer` | reviewer_1 | Peer Reviewer |
| `engineering_manager` | manager_1 | Engineering Manager |
| `synthesizer` | synthesizer_1 | Synthesis Agent |
| `generalist` | generalist_1 | General-purpose Assistant |

Users override by defining the same key in `souls:` section. Soul files (`.md`) can be referenced: `soul_ref: file:./souls/researcher.md` for loading system prompt from file.

---

### 3.2 Auto-Discovery

#### 3.2.1 Directory Layout

```
workspace/
├── workflows/
│   └── research_review.yaml
├── custom/
│   ├── my_blocks.py      # Defines MyCustomBlock, AnotherBlock
│   └── vendor/
│       └── vendor_block.py
└── phalanx.yaml          # Optional: config, custom_dir path
```

**Configurable paths:**
- `PHALANX_CUSTOM_DIR` env var (default: `./custom`)
- Or `config.custom_dir` in root `phalanx.yaml`

#### 3.2.2 Discovery Algorithm

```
Algorithm: discover_custom_blocks(custom_dir) → BlockRegistry
──────────────────────────────────────────────────────────
1. registry = BlockRegistry()
2. Register built-in blocks: registry.register("linear", ...), etc.
3. For each .py file in custom_dir (recursive):
   a. module_name = path_to_module(file_path)
   b. module = importlib.import_module(module_name)
   c. For each attr in dir(module):
        if isinstance(getattr(module, attr), type):
            cls = getattr(module, attr)
            if issubclass(cls, BaseBlock) and cls is not BaseBlock:
                block_id = getattr(cls, "block_id", None) or to_snake_case(cls.__name__)
                factory = lambda sid, desc, _cls=cls: _cls(sid, desc)  # Or from config
                registry.register(block_id, factory)
4. RETURN registry
```

#### 3.2.3 BlockRegistry Factory Signature

The existing `BlockRegistry` expects `BlockFactory = Callable[[str, str], BaseBlock]` (block_id, description) for **dynamic injection**. For **YAML static blocks**, the parser needs to pass full config (e.g., `soul_ref`, `iterations`). Two options:

- **Option A:** Extend factory signature to `Callable[[str, str | Dict], BaseBlock]` — second arg is `description` (injection) or `config` dict (YAML). Factory branches on type.
- **Option B:** Separate registries — `BlockRegistry` for injection (existing); `BlockTypeRegistry` for YAML parsing (type string → factory that receives config dict). Custom blocks register in both.

**Recommendation:** Option B — keep `BlockRegistry` unchanged for injection; add `BlockTypeRegistry` for YAML. Auto-Discovery populates both: for injection, register `lambda sid, desc: MyBlock(sid, description=desc)`; for YAML, register `lambda bid, cfg: MyBlock(bid, **cfg)`.

#### 3.2.4 Custom Block Contract

A discoverable block must:

1. Inherit from `BaseBlock`
2. Be defined at module level (not nested inside another class)
3. Have a constructor compatible with `(block_id: str, **config)` — the factory may pass `description` for injection, or full config from YAML

**Example custom block:**

```python
# custom/my_blocks.py
from phalanx_core.blocks.base import BaseBlock
from phalanx_core.state import WorkflowState

class MyCustomBlock(BaseBlock):
    """Custom block that does X. Auto-registered as 'my_custom_block'."""

    def __init__(self, block_id: str, description: str = "", **kwargs):
        super().__init__(block_id)
        self.description = description
        self.config = kwargs

    async def execute(self, state: WorkflowState) -> WorkflowState:
        # Custom logic
        result = f"Processed: {state.current_task.instruction if state.current_task else self.description}"
        return state.model_copy(
            update={
                "results": {**state.results, self.block_id: result},
                "messages": state.messages + [{"role": "system", "content": f"[{self.block_id}] Done"}],
            }
        )
```

#### 3.2.5 YAML Integration for Custom Blocks

In YAML, custom blocks are referenced by their discovered ID:

```yaml
blocks:
  custom_step:
    type: my_custom_block  # From custom/my_blocks.py
    description: "Optional config"
    some_option: true
```

The parser looks up `type` in the merged registry (built-in + discovered). If found, it invokes the factory with `block_id` and the block's config dict.

#### 3.2.6 Security Considerations

- **Import isolation:** Discovery uses `importlib`; modules execute at import time. Malicious code in `custom/` can run arbitrary Python. **Recommendation:** Document that `custom/` is trusted; for untrusted plugins, use a sandboxed loader (Phase 2).
- **Naming collisions:** If a custom block uses the same ID as a built-in, custom overrides. Document reserved IDs.
- **Discovery order:** Built-in blocks registered first; custom blocks can override by re-registering (last-wins).

---

### 3.3 API & MCP Server

#### 3.3.1 FastAPI Endpoints

| Method | Path | Description |
|--------|------|--------------|
| GET | `/health` | Health check |
| GET | `/workflows` | List loaded workflow IDs and names |
| GET | `/workflows/{workflow_id}` | Get workflow schema (blocks, transitions, entry) |
| POST | `/workflows/{workflow_id}/run` | Execute workflow with task input |
| GET | `/blocks` | List available block types (built-in + custom) |
| GET | `/souls` | List available soul definitions (if exposed) |

**Run request body:**

```json
{
  "task_instruction": "Review the following code for security issues.",
  "task_context": "def foo(): pass",
  "task_id": "optional-custom-id"
}
```

**Run response:**

```json
{
  "workflow_id": "research_review",
  "status": "completed",
  "results": { "initial_research": "...", "review_gate": "approved" },
  "messages": [...],
  "error": null
}
```

#### 3.3.2 MCP Server Design

**Technology:** `mcp` Python package (official Model Context Protocol SDK).

**Tool schema per workflow:**

```json
{
  "name": "phalanx_run_research_review",
  "description": "Run the Research Review Pipeline workflow. Pass the task instruction and optional context.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task_instruction": { "type": "string", "description": "The main task instruction" },
      "task_context": { "type": "string", "description": "Optional additional context" }
    },
    "required": ["task_instruction"]
  }
}
```

**MCP Server lifecycle:**

1. On startup, load workflows from configured directory (e.g., `workflows/*.yaml`)
2. Parse each into `Workflow` instance
3. Register each workflow as an MCP tool via SDK
4. On tool call from client: execute `workflow.run(WorkflowState(current_task=Task(...)))`, return summary

**Transport options:**

- **stdio:** Default for Cursor/Claude Desktop — server runs as subprocess, communicates via stdin/stdout
- **HTTP/SSE:** For remote clients (Langsmith, custom integrations)

#### 3.3.3 MCP Tool Implementation Sketch

```python
# Pseudocode
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("phalanx")

@mcp.tool()
async def phalanx_run_research_review(task_instruction: str, task_context: str = "") -> str:
    """Run the Research Review Pipeline workflow."""
    workflow = workflow_registry.get("research_review")
    state = WorkflowState(current_task=Task(id="run_1", instruction=task_instruction, context=task_context or None))
    final_state = await workflow.run(state, registry=block_registry)
    return json.dumps({"results": final_state.results, "messages_summary": len(final_state.messages)})
```

Dynamic registration: iterate over loaded workflows and call `mcp.tool()` (or equivalent) for each.

#### 3.3.4 Cursor/Claude Integration

**Cursor:** Add to `.cursor/mcp.json` or equivalent config:

```json
{
  "mcpServers": {
    "phalanx": {
      "command": "phalanx",
      "args": ["mcp-server"],
      "env": { "PHALANX_WORKFLOWS_DIR": "./workflows" }
    }
  }
}
```

**Claude Desktop:** Similar config in Claude's MCP settings; `phalanx mcp-server` runs the MCP stdio server.

---

## 4. Example User Flow

### 4.1 Non-Developer: Run Workflow via YAML

1. **Create workflow file** `workflows/code_review.yaml`:
   ```yaml
   version: "1.0"
   souls:
     reviewer:
       id: rev_1
       role: Code Reviewer
       system_prompt: "You review code for bugs and style."
   blocks:
     review:
       type: linear
       soul_ref: reviewer
   workflow:
     name: CodeReview
     entry: review
     transitions: [{ from: review, to: null }]
   ```

2. **Run via CLI** (Phase 1.4 extends CLI):
   ```bash
   phalanx run workflows/code_review.yaml --task "Review this function: def foo(): pass"
   ```

3. **Or run via API**:
   ```bash
   curl -X POST http://localhost:8000/workflows/code_review/run \
     -H "Content-Type: application/json" \
     -d '{"task_instruction": "Review this function: def foo(): pass"}'
   ```

### 4.2 Developer: Add Custom Block

1. **Create** `custom/sentiment_block.py`:
   ```python
   from phalanx_core.blocks.base import BaseBlock
   from phalanx_core.state import WorkflowState

   class SentimentBlock(BaseBlock):
       async def execute(self, state: WorkflowState) -> WorkflowState:
           # Placeholder: in reality, call sentiment API
           sentiment = "positive"
           return state.model_copy(update={
               "results": {**state.results, self.block_id: sentiment},
               "messages": state.messages + [{"role": "system", "content": f"Sentiment: {sentiment}"}],
           })
   ```

2. **Use in YAML**:
   ```yaml
   blocks:
     sentiment_check:
       type: sentiment_block
   ```

3. **Start server** — block is auto-discovered and available.

### 4.3 AI Client (Cursor): Invoke via MCP

1. **Configure Cursor** with Phalanx MCP server (see 3.3.4).

2. **User asks Cursor:** "Run the research review workflow to analyze the benefits of microservices."

3. **Cursor** discovers `phalanx_run_research_review` tool, calls it with:
   ```json
   {"task_instruction": "Analyze the benefits of microservices architecture"}
   ```

4. **Phalanx** executes the workflow, returns results to Cursor.

5. **Cursor** presents the outcome to the user.

---

## 5. Implementation Phases (Suggested)

| Phase | Deliverable |
|-------|-------------|
| **1.4a** | YAML parser: souls, blocks (linear, fanout, router, synthesize), workflow topology. Parse to `Workflow` + validate. |
| **1.4b** | Standard Library: Soul library, block type registry. Extend parser for all built-in block types. |
| **1.4c** | Auto-Discovery: `custom/` directory scan, `BaseBlock` subclass detection, `BlockRegistry` registration. |
| **1.4d** | FastAPI: `/workflows`, `/workflows/{id}/run`, health. Load workflows from configurable directory on startup. |
| **1.4e** | MCP Server: `phalanx mcp-server` command, tool registration per workflow, stdio transport. |
| **1.4f** | CLI integration: `phalanx run <workflow.yaml> --task "..."` for running YAML workflows from terminal. |

---

## 6. Summary

Phase 1.4 exposes Phalanx through:

- **YAML/JSON Parser** — Declarative workflow definition with souls and blocks; parser produces runnable `Workflow` instances.
- **Auto-Discovery** — `custom/` directory convention; Python files with `BaseBlock` subclasses are automatically registered in `BlockRegistry`.
- **FastAPI** — REST endpoints for listing and running workflows.
- **MCP Server** — Each workflow exposed as a tool; external AIs (Cursor, Claude Desktop) can discover and invoke Phalanx workflows natively.

The design preserves the existing programmatic Python API and aligns with Phase 1.3's dynamic graph capabilities (conditional transitions, dynamic injection). Custom blocks participate in both static YAML workflows and dynamic injection via the shared registry.
