# Phalanx Future Roadmap (Post v1.0.0)

This document outlines the major phases and features planned for Phalanx after the v1.0.0 CLI/Backend stabilization.

## Phase 1.1: Core Orchestration Features (The "Wiring Up" Phase)
The foundational engines for these features exist in the codebase but need to be formally wired into the `TeamMonitor` execution loop:
* **DAG Orchestrator Integration**: Actively use `phalanx/skills/orchestrator.py` to schedule and execute steps dynamically, rather than just spinning up parallel agents.
* **Cost Tracking Integration**: Connect the `CostAggregator` (`phalanx/costs/`) to intercept token usage from agent streams/artifacts and record them to the database continuously.
* **Continual Learning / Context Injection**: Implement the `TeamContextStore` (`phalanx/learning/`) to extract context from completed artifacts and inject them into subsequent agent resumes to prevent drift and repeat failures.
* **Git Worktrees**: Finish wiring up `phalanx/process/worktree.py` to support true isolation for parallel workers on the same repo.
* **Engineering Manager (Outer Loop)**: Fully activate the `EngineeringManager` skill to trigger dynamically when the `FailureEscalator` reaches the outer loop.

## Phase 1.2: Advanced Orchestration
* **Checkpoint/Resume at Step Level**: Implement fine-grained DAG checkpointing so that resumed agents skip completely executed tasks.
* **Dynamic DAG Replanning**: Allow the Engineering Manager to rewrite the active DAG on the fly (adding/removing steps) in response to failure.

## Phase 2: User Interface (UI)
* **Web/Desktop GUI**: A graphical interface for monitoring teams, viewing the DAG, and interacting with the team feed.
* **Visual Replanning**: Allowing the human operator to visually modify the execution graph or swap models.

## Phase 3: Advanced Optimizations & LiteLLM Integration
* **Backend Hot-Swapping**: The ability to dynamically change an agent's underlying backend (e.g., from Cursor to Claude Code to a LiteLLM proxy) mid-task.
* **Context Serialization (Enhanced Prompt-Replay)**: To support hot-swapping without losing the agent's "chain of thought", the `CheckpointManager` will generate a structured `context_summary`. When swapped to a new backend, the new agent will receive this summary + completed DAG artifacts + remaining tasks.
* **LiteLLM Native Integration**: A dedicated `phalanx/backends/litellm.py` integration to support a wider array of open-source and proprietary models natively, decoupled from proprietary CLI tools.