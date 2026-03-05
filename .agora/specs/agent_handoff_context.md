# Phalanx Agent Handoff Context

## 1. Project Goal & Current State
The user is developing **Phalanx**, a Python-based "Operating System for Agents" (Meta-Framework) capable of dynamically building domain-specific workflows. It uses a LangGraph-inspired Workflow State Machine.

**Completed Phases:**
*   **Phase 1.1:** Core Primitives (`Soul`, `Task`, `LiteLLMClient`, `Runner`).
*   **Phase 1.2:** The Blueprint Engine (DAG, Blocks like `LinearBlock`, `FanOutBlock`, `MessageBusBlock`, `TeamLeadBlock`, `EngineeringManagerBlock`, `RouterBlock`). Renamed `Blueprint` to `Workflow` and removed `Skill`.
*   **Phase 1.3:** Dynamic Graph Engine (Conditional Branching, Dynamic Step Injection, `PlaceholderBlock`).
*   **Phase 1.4:** API & Extensibility Layer (YAML Parser, Auto-Discovery of custom assets, MCP Server, Cost Tracking).
*   **Phase 1.5:** Task Engine & Headless API (Declarative YAML execution, `phalanx run`, FastAPI REST endpoints).

**Current Phase:**
*   **Phase 1.6:** UI & Visual Builder. The user wants to build a React/Next.js UI to visualize, create, and manage workflows.

## 2. Key Decisions & Paradigms

### The Unified `Task` Primitive
Previously, we discussed exposing `Task` (what to do) and `Skill`/`Tool` (how to do it) separately. 
**Decision:** The user found this too complex for non-programmers. We are unifying them. 
A `Task` is now the ultimate primitive that bundles:
1.  **Instruction** (Prompt)
2.  **Capabilities** (Tools/Skills)
3.  **Output Routing** (Where the result goes: workspace, mcp, webhook, etc.)

We aborted renaming `Task` to `Action`. The UI will present these as pre-packaged "Smart Tasks".

### GitOps Architecture
Phalanx uses a GitOps approach. Workflows, Souls, and Tasks are defined as YAML files stored in the filesystem (`custom/`). The Phase 1.5 FastAPI server treats the filesystem as its primary database for definitions.

## 3. UI/UX Design Feedback (Phase 1.6)
We designed a high-fidelity HTML mockup for the UI. The user provided the following 8 critical points of feedback which MUST guide the UI development:

1.  **No "Tools" in sidebar:** The "Tools" tab should be removed as tools are not top-level primitives.
2.  **Editing Souls:** Allow editing of Souls. If a default soul is edited, it should create a local `custom/soul` override.
3.  **API Providers & Models:** Need a global settings modal for API keys (`.env`) and model selection (dropdown of common models + raw text input for custom ones).
4.  **DAG vs State Machine Toggle:** Remove the toggle; the engine is inherently dynamic, so it's all one unified "Workflow".
5.  **Right Drawer Tabs:** Rename "Properties" to "Configuration" (for block type, retry, output routing) and "Prompt/Task" to "Prompt." "Raw YAML" should be a read-only view.
6.  **"product_spec" Output Key:** This will be replaced by the new "Output Routing" concept.
7.  **"Commit" Button:** Confirmed it commits YAML configs to Git, not run results.
8.  **No Authentication:** Remove the user avatar ("MR") as there is no auth for this local tool.

## 4. Immediate Next Steps
The user is ready to begin work on the Phase 1.6 UI development, utilizing a visual feedback loop (e.g., Playwright/screenshots) to iteratively build the React interface according to the design spec and feedback above.