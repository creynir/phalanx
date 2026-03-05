# Phalanx Phase 1.5/1.6 — Unifying Task, Skill, and Tools for UX

## 1. The Problem: Conceptual Overload

As we build Phalanx for non-programmers or regular users building workflows, exposing the internal separation of `Task` (What to do), `Skill` (How to do it), and `Tool` (The specific function called) creates a UX nightmare. 

If a user wants an agent to search the web, they shouldn't have to:
1. Create a `Task` ("Search the web").
2. Assign a `Skill` ("WebResearchSkill").
3. Ensure the `Skill` has access to the `Tool` ("TavilySearchAPI").

**This is too complex.** A task is not just an instruction; to the user, a task *includes* the capability to do it.

## 2. The UX Solution: Task as the Ultimate Primitive

From a product perspective, we need to flatten this hierarchy for the user, while keeping the engine robust under the hood.

**A `Task` should represent a bounded unit of work that ALREADY bundles the instruction and the required capabilities.**

### 2.1 The "Standard Library" of Tasks

Instead of having a blank "Task" node where users type instructions and manually attach skills, Phalanx will provide a library of pre-configured **Tasks**. 

Examples of Drag-and-Drop Tasks:
- **`Write Code` Task**: Automatically bundles a generic coder prompt + Workspace File Tools.
- **`Search Web` Task**: Automatically bundles a generic researcher prompt + Tavily/Google Search Tools.
- **`Review PR` Task**: Automatically bundles a reviewer prompt + GitHub MCP Tools.
- **`Custom Task`**: A blank slate where power users can write a custom prompt and manually select tools from a dropdown.

### 2.2 Unifying the YAML

Under the hood, the `Task` YAML schema becomes the single source of truth for both *instruction* and *capability*.

```yaml
# custom/tasks/web_research.yaml
version: "1.0"
task:
  id: web_research
  title: Search the Web
  
  # The "What" (Instruction)
  instruction: |
    Search the internet for the following query: {{ input.query }}
    Summarize the top 3 results.
  
  # The "How" (Capabilities/Skills/Tools)
  tools:
    - mcp: "brave_search_server"
      endpoint: "/search"
  
  # The "Where" (Output - replacing the Action rename)
  output:
    type: artifact_only
```

## 3. Product Impact (The UI)

When a user opens the Phalanx Canvas, the Left Sidebar will look like this:

**Sidebar Tabs:**
1. **Souls** (Who)
2. **Tasks** (What + How)

**Inside the Tasks Tab:**
- *Web Search*
- *Read File*
- *Write Code*
- *Send Slack Message*
- *Custom Blank Task*

When the user drags "Web Search" onto the canvas, they don't need to know what an MCP server is. The `Task` node already contains the system prompt for searching and the tool binding. They just connect the wires.

## 4. Conclusion

- We **abort** renaming `Task` to `Action`. 
- We **abort** introducing `Skill` as a user-facing primitive.
- We **elevate** `Task` to encompass both the Prompt AND the Tools/Output routing. 
- The UI will present pre-packaged "Smart Tasks" to abstract away the complexity of tool binding for non-technical users.
