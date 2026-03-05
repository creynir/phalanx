# SWE-AF Architecture Deep Dive

**Target:** `SWE-AF` (Agent-Field)  
**Date:** March 2026

## 1. Executive Summary
SWE-AF is an agentic framework designed to build software. It implements a layered, cyclic orchestration model (Actor-Critic) driven by a control plane. Unlike standard DAGs, SWE-AF supports internal back-and-forth loops, but these loops are mostly hardcoded in Python logic rather than dynamically defined in a declarative graph.

## 2. Core Components

- **Control Plane**: The central orchestrator that parses the original goal and breaks it down.
- **Agent Roles**: Specialized agents (PM, Architect, Tech Lead, Coder, Reviewer).
- **Merger Agent**: An intelligent agent dedicated to resolving semantic Git conflicts and merging parallel workstreams.
- **Git Worktrees**: SWE-AF utilizes isolated Git worktrees (`.worktrees/` dir) to run parallel coders on the same repository without stepping on each other's toes. 

## 3. The 3-Tiered Control Loop

SWE-AF operates in a hybrid model:
1. **Outer DAG (Linear Execution)**: The high-level plan (e.g., Plan -> Code -> Review -> Merge). This resembles a standard static DAG.
2. **Inner Cyclic Loops (Actor-Critic)**: Inside the code/review phases, SWE-AF runs hardcoded `while` or `for` loops. For instance, the `run_tech_lead` function iterates `max_review_iterations` times, passing code back to the coder if rejected.
3. **Network Layer**: Uses `agentfield` for networking and message passing, with an internal dependency on `litellm` to normalize provider access.

## 4. Contrast with Phalanx

| Feature | SWE-AF | Phalanx (Target) |
|---------|--------|-------------------|
| **Orchestration** | Hardcoded Python loops | Declarative Workflow Engine |
| **Generality** | SWE only (code generation) | Domain agnostic (Meta-Framework) |
| **Loops** | Hardcoded Actor-Critic | `RetryBlock`, `MessageBusBlock` (Swarm) |
| **State** | Implicit in files / Python memory | Explicit `WorkflowState` object |

## 5. Key Takeaways for Phalanx
- **Worktrees**: The approach to isolated Git worktrees is brilliant for parallel execution and should be adopted in Phalanx for complex code-generation tasks (Phase 2+).
- **Merger Agent**: Conflict resolution requires an intelligent agent, not just a standard Git merge.
- **Standardized Networking**: SWE-AF using `litellm` validates our decision to standardize on it.