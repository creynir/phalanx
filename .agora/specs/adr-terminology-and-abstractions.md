# ADR: Terminology & Abstractions Research

**Date:** March 2026
**Context:** Phase 1.2

During the transition to the Meta-Framework architecture, we conducted research into industry standards and evaluated several abstractions (`Skill`, `Blueprint`, `Step`, `Block`) to ensure our terminology aligns with non-technical user expectations and industry norms.

## 1. The "Skill" Abstraction
**Research:** We analyzed how the industry uses the term "Skill" (e.g., Semantic Kernel, AutoGen, CrewAI). In most agent frameworks, a "Skill" denotes a discrete capability or a specific tool (e.g., "Web Search Skill", "Python Execution Skill"). 
**Initial Proposal:** We initially introduced `Skill` as a wrapper around a full Directed Acyclic Graph (DAG) of tasks. 
**Decision:** **REJECTED.** Calling a massive multi-agent DAG pipeline a "Skill" is confusing and clashes with industry norms. We have deleted the `Skill` primitive entirely. 

## 2. Blueprint vs. Workflow
**Research:** We needed a term for the overarching graph/pipeline that non-technical users could easily understand. We initially used `Blueprint`.
**Decision:** **MAPPED TO WORKFLOW.** We renamed `Blueprint` to `Workflow`. This perfectly aligns with industry-standard CI/CD tools (like GitHub Actions and CircleCI), where users are already accustomed to defining "Workflows".

## 3. Step vs. Block
**Research & Evaluation:** There was confusion over what to call the nodes in the graph and the execution logic within them. Should a graph node be a Step or a Block?
**Decision:** **KEPT BOTH, SEPARATED CONCERNS.**
- **Step**: The Graph Node. It acts as the orchestration wrapper. A Step manages standard deterministic Python execution: it runs `pre_hooks`, manages transitions, and runs `post_hooks`.
- **Block**: The Execution Engine. It lives *inside* a Step. Blocks (`LinearBlock`, `MessageBusBlock`, `RouterBlock`) define *how* agents behave and interact with LLMs, completely ignorant of the broader graph structure.
*User Feedback Incorporated:* "Workflow should consist of steps. But I want to keep block as a logical unit. So the step can have blocks inside."

## 4. Souls and Tasks
**Decision:** Retained as core primitives.
- **Soul**: Defines the agent's persona, system prompt, and allowed tools.
- **Task**: The specific isolated instruction (and context) handed to a Soul for execution at runtime.
