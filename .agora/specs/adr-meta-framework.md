# ADR: The Phalanx Meta-Framework

**Date:** March 2026

## 1. Context & Problem
The user initially requested to implement a Directed Acyclic Graph (DAG) for orchestrating agents. However, typical static DAGs (like GitHub Actions) are insufficient for AI workloads, which require loops, retries, and dynamic pathing (e.g., Code -> Review -> Back to Code).

We observed two existing paradigms:
1. **LangGraph StateMachine**: Excellent for cycles, but highly complex to define natively in Python, especially for non-technical users.
2. **SWE-AF Hybrid**: Outer DAG with hardcoded internal loops. Great for specific tasks (like coding), but not generalized.

## 2. Decision
We will evolve Phalanx into a **Meta-Framework** (an "Operating System for Agents"). 

Instead of writing bespoke python loops for every use case, we will build a generic **Workflow Engine**. Users will assemble declarative pipelines out of standard, generic **Blocks**.

### Core Philosophy: Separation of Orchestration and Execution
- **Workflow**: The overarching graph structure.
- **Step**: The node in the graph. It handles orchestration (calling `pre_hooks`, invoking the block, calling `post_hooks`).
- **Block**: The actual execution engine (e.g., `LinearBlock`, `MessageBusBlock`, `RouterBlock`). Blocks contain the logic for *how* agents interact, but know nothing about the surrounding graph.

## 3. Consequences
1. **Generality**: By creating a library of generic blocks, we can support any domain (SWE, Marketing, Research) without changing the core engine.
2. **Predictability**: The engine is purely deterministic. The non-determinism (LLM behavior) is strictly boxed inside the execution of individual Blocks.
3. **Simplicity**: Users (eventually via GUI) can snap these Lego blocks together easily.