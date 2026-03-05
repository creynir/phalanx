# Phalanx Architecture & Design Record

**Last Updated:** March 2026
**Current Phase:** 1.2e (Core Simplification)

## 1. Executive Summary
Phalanx is evolving from a tightly coupled CLI tool into a generalized "Operating System for AI Agents" (a Meta-Framework). The goal is to provide a robust, deterministic execution engine (Core) that supports complex agentic workflows, separating execution logic from the user interface (API/GUI/CLI).

## 2. Core Concepts & Terminology (Phase 1.2e)
To ensure the system remains maintainable and accessible to both technical and non-technical users, we enforce a strict separation of concerns:

- **Workflow**: The overarching Directed Acyclic Graph (DAG). Represents a full pipeline (e.g., "Quality Assurance Pipeline").
- **Step**: A node on the Workflow graph. It acts as an orchestration wrapper, managing execution order and running synchronous `pre_hooks` and `post_hooks` (standard Python).
- **Block**: The internal execution engine inside a Step (e.g., `MessageBusBlock`, `RouterBlock`). Blocks define *how* an agent acts (Linear, FanOut, Debate) and are unaware of the broader graph.
- **Task**: The specific instruction and context (e.g., "Review this code diff") given to an agent at runtime.
- **Soul**: The persona, system prompt, and tool-access permissions of the agent.

## 3. High-Level Architecture (The Stack)
1. **Model Layer**: `LiteLLM` abstracts all underlying provider APIs (Anthropic, OpenAI, Local).
2. **Execution Layer**: `phalanx-core` (Python). Executes `Workflows`, `Steps`, and `Blocks`. Manages state and memory.
3. **Interface Layer**: 
    - `phalanx-cli` (Terminal UI, thin client)
    - Phalanx API (FastAPI backend)
    - MCP Server (Model Context Protocol for AI-to-AI interaction)
    - Phalanx GUI (Next.js visual builder)

## 4. Phase 1.3: Dynamic Graph Engine (Design Spec)
*Note: This phase is implemented and active.*

### Objectives
Transform the static Workflow runner into a dynamic state machine capable of self-healing and branching.

### Mechanisms
1. **Dynamic Routing**:
   - `RouterBlock` outputs decisions (e.g., "approved", "rejected") into `state.metadata["router_decision"]`.
   - The Engine reads this metadata and evaluates conditional transitions to determine the next `Step`.
2. **Dynamic Step Injection (Self-Healing)**:
   - When encountering an unknown, an `EngineeringManagerBlock` generates a JSON list of new steps.
   - The Engine intercepts this, verifies the steps exist in the `BlockRegistry`, and splices them into the active Workflow on the fly.
3. **Hallucination Protection**:
   - If an agent hallucinates a non-existent step, the Engine fails the injection and loops back to a `RetryBlock` wrapping the manager, forcing it to correct its output.

## 5. Phase 1.4: API & Extensibility Layer (Planned)
See [Phase 1.4 Spec](../.agora/specs/phase-1.4-api-and-extensibility.md) for full design.
- **Standard Library & YAML Parser**: Non-technical users define Workflows, Souls, and Tasks in YAML/JSON; parser produces runnable Python objects.
- **Auto-Discovery**: `custom/` directory convention — Python files with `BaseBlock` subclasses are automatically discovered and registered in `BlockRegistry`.
- **FastAPI & MCP Server**: REST API for listing/running workflows; MCP exposure so external AIs (Cursor, Claude Desktop, Langsmith) can discover and trigger workflows as tools.

## 6. Phase 1.5 & 1.6: Production Readiness (Planned)
- **Visual GUI**: Drag-and-drop workflow builder.
- **Cost Tracking**: Enforce token/dollar budgets per Workflow.
- **Auto-Learning Memory**: Store successful error-recovery trajectories in a vector database. Future errors will query this DB to pull known fixes deterministically.
- **Human-in-the-loop (HITL)**: Implement `ApprovalBlock` to pause execution for destructive actions or budget extensions.