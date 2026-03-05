# Research: LiteLLM vs Provider SDKs (Anthropic/OpenAI)

**Date:** March 2026

## 1. Context
During the analysis of the SWE-AF (Agent-Field) repository, we noticed that it relies on `litellm` internally for its networking layer, but also directly integrates with the Anthropic API in some places. 

The user asked: *"Why does SWE-AF have litellm integration alongside anthropic API integration? Why not use LiteLLM for everything? Should we do the same?"*

## 2. Analysis of SWE-AF's Approach
SWE-AF's dual-dependency approach is largely an artifact of rapid development and specific model features rather than a deliberate, clean architectural choice:
1. **LiteLLM Usage**: SWE-AF uses the `agentfield` library under the hood, which strictly uses `litellm` to normalize provider access (allowing users to swap between OpenAI, Anthropic, Gemini, etc.).
2. **Direct Provider Usage**: In certain control loops or specialized agents, SWE-AF bypassed `litellm` to use the native Anthropic SDK, likely to access beta features, specific prompt caching mechanisms, or tools (like computer-use) that `litellm` had not fully supported at the time of authoring.

## 3. Decision for Phalanx
**Should Phalanx do the same (mix LiteLLM and native SDKs)?**

**NO.** We will use **LiteLLM exclusively** as our single unified interface layer for all LLM calls.

### Reasoning:
- **Maintainability:** Mixing SDKs fragments the codebase. If we need to implement retry logic, budget tracking, or telemetry, doing it across `litellm`, `openai`, and `anthropic` SDKs simultaneously violates DRY principles.
- **LiteLLM Maturity:** LiteLLM now natively supports advanced Anthropic features (Prompt Caching, Tool Calling, Vision, etc.). There is no longer a technical justification to bypass it.
- **Portability:** Our goal as a Meta-Framework is to allow users to hot-swap models at the `Block` level. If a block hardcodes the Anthropic SDK, that block can never be run by a local Llama model or OpenAI's GPT-4o. 

## 4. Conclusion
Phalanx will strictly route all LLM communication through `phalanx_core.llm.client.LiteLLMClient`, which wraps `litellm.acompletion` and `litellm.astream_chat`. Direct provider SDKs will not be imported into core logic.