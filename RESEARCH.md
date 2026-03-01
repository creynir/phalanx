# Research: Intercepting, Proxying, and Injecting Messages into CLI Agent Processes

## 1. Telemetry in LangGraph/LangSmith
**Mechanism:** API Hooks and Callbacks
LangGraph and LangSmith primarily gather telemetry using native SDK integration (Python/TypeScript). The SDKs provide built-in tracing callbacks that hook deeply into the LLM execution lifecycle (e.g., `on_chat_model_start`, `on_tool_start`). For agents that do not use the SDK directly, LangSmith offers a proxy approach where the agent's base URL is configured to point to a LangSmith proxy. The proxy logs the request payload and forwards it to the actual LLM provider (OpenAI, Anthropic, etc.). They **do not** rely on fragile `stdin/stdout` interception for telemetry.

## 2. Wrapping CLI Agents for Message Injection
**Mechanism:** TTY Wrappers (Pseudoterminals) vs. Network Proxies
It is possible to wrap CLI agent processes to inject additional context or messages:
- **TTY/StdIO Wrappers:** Tools like `pexpect` (Python) or `node-pty` (Node.js) can intercept a CLI's `stdout` and inject keystrokes into its `stdin` via a pseudoterminal. This is useful for simulating user input but is brittle against UI changes (like spinners or raw terminal escape codes).
- **Network Proxies:** A more robust method for injecting *context* is to run the CLI through a local HTTP/HTTPS proxy. By modifying the outgoing JSON payload of the API requests, an orchestrator can append hidden system prompts or context without the CLI tool's UI knowing about it.

## 3. MITM Proxy Approach on HTTP/WebSocket
**Mechanism:** `mitmproxy` Payload Modification
Yes, a Man-In-The-Middle (MITM) proxy can be used on the HTTP layer between the CLI and the API. By setting `HTTPS_PROXY=http://127.0.0.1:8080` and configuring the OS or the CLI runtime (e.g., `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`) to trust a custom root CA certificate, tools like `mitmproxy` can intercept `POST /v1/chat/completions`.
- **Injection:** A custom proxy script can decode the JSON request, locate the `messages` array, and inject a new `{"role": "user", "content": "injected background context"}` object before forwarding the request to the upstream API.
- **Challenges:** Certificate pinning (if the CLI hardcodes trusted root certs, the MITM connection will be rejected) and complex state management over WebSocket connections (e.g., Cursor's real-time streaming).

## 4. Stdin Piping and Stream-JSON Input Modes
**Mechanism:** Programmatic Stream Interfaces
Many modern CLI agents are adopting structured input modes to solve the orchestration problem natively:
- **Claude Code:** Supports rich programmatic inputs, including reading from `stdin`. If invoked with an `--input-format stream-json` flag, it allows an external orchestrator to continuously pipe structured JSON-lines (JSONL) representing events, file changes, or new messages directly into the agent's event loop.
- **Gemini / Codex CLIs:** Standard POSIX CLIs generally support reading from `stdin` (e.g., `echo "prompt" | gemini`). Advanced modes allow JSON-lines for continuous streaming of I/O without needing to restart the process.
- **Cursor:** Cursor's agent is tightly integrated into its IDE's extension host. Intercepting it usually requires either an extension within Cursor or MITM network proxying, as it does not operate as a standalone standard input/output terminal CLI.

## 5. Open Source Solutions for the "Send Message to Running Agent" Problem
**Mechanism:** Standardized Protocols and Orchestration Frameworks
- **Agent Protocol (`agentprotocol.ai`):** An open standard designed to solve exactly this problem. It standardizes how agents communicate, allowing external systems to send messages to running agents via standard REST/WebSocket APIs, bypassing the need to hack `stdin/stdout`.
- **Frameworks (AutoGen, CrewAI, LangGraph):** These existing multi-agent frameworks generally avoid wrapping opaque CLIs. Instead, they define agents programmatically (via code objects) so they have direct, native access to the message arrays, shared memory, and state. When they do need to interact with external tools, they prefer structured API endpoints over terminal scraping.
