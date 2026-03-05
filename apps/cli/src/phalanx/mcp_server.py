"""
Phalanx MCP Server.
Exposes each discovered workflow as an MCP tool for Cursor/Claude Desktop.
Transport: stdio (default in mcp>=1.0.0, per specification).
"""

import json
import logging
from pathlib import Path
from typing import Dict

from mcp.server.fastmcp import FastMCP

from phalanx_core.primitives import Task
from phalanx_core.state import WorkflowState
from phalanx_core.workflow import Workflow
from phalanx_core.yaml import parse_workflow_yaml

logger = logging.getLogger(__name__)


def _load_workflows(workflows_dir: str) -> Dict[str, Workflow]:
    """
    Load all .yaml workflow files from workflows_dir.

    Returns dict keyed by sanitized workflow name (tool name suffix).
    Files that fail to parse are logged and skipped — no exception raised.
    """
    wf_path = Path(workflows_dir)
    workflows: Dict[str, Workflow] = {}

    if not wf_path.exists():
        logger.warning("Workflows directory '%s' does not exist.", workflows_dir)
        return workflows

    for yaml_file in wf_path.glob("*.yaml"):
        try:
            wf = parse_workflow_yaml(str(yaml_file))
            # Sanitize: lowercase, spaces and hyphens to underscores
            sanitized = wf.name.lower().replace(" ", "_").replace("-", "_")
            workflows[sanitized] = wf
            logger.info("Loaded workflow '%s' → tool 'phalanx_run_%s'", wf.name, sanitized)
        except Exception as exc:
            logger.warning("Failed to load workflow from '%s': %s", yaml_file, exc)

    return workflows


def create_mcp_server(workflows_dir: str = "./workflows") -> FastMCP:
    """
    Create a FastMCP server with one tool registered per discovered workflow.

    Tool naming convention: phalanx_run_{sanitized_workflow_name}
    Tool input parameters:
        task_instruction: str          — required, the main task for all agents
        task_context: str = ""         — optional, additional context
    Tool return value:
        str — JSON with keys: results (dict), messages_summary (int),
              cost_usd (float), total_tokens (int)

    Args:
        workflows_dir: Path to directory containing .yaml workflow files.

    Returns:
        Configured FastMCP instance. Call .run() to start stdio transport.
    """
    mcp = FastMCP("phalanx")
    workflows = _load_workflows(workflows_dir)

    for wf_name, workflow in workflows.items():
        tool_name = f"phalanx_run_{wf_name}"

        # _make_tool creates a fresh function scope per workflow,
        # preventing Python loop closure capture bug
        def _make_tool(wf: Workflow, name: str) -> None:
            async def run_workflow(task_instruction: str, task_context: str = "") -> str:
                state = WorkflowState(
                    current_task=Task(
                        id="mcp_run",
                        instruction=task_instruction,
                        context=task_context if task_context else None,
                    )
                )
                final_state = await wf.run(state)
                return json.dumps(
                    {
                        "results": final_state.results,
                        "messages_summary": len(final_state.messages),
                        "cost_usd": final_state.total_cost_usd,
                        "total_tokens": final_state.total_tokens,
                    }
                )

            run_workflow.__name__ = name
            run_workflow.__doc__ = (
                f"Run the '{wf.name}' Phalanx workflow.\n\n"
                f"Args:\n"
                f"    task_instruction: The main task instruction for all agents.\n"
                f"    task_context: Optional additional context (empty string if none).\n\n"
                f"Returns:\n"
                f"    JSON string with: results (block outputs), messages_summary (int), "
                f"cost_usd (float), total_tokens (int)."
            )
            mcp.tool()(run_workflow)

        _make_tool(workflow, tool_name)

    return mcp


def run_mcp_server(workflows_dir: str = "./workflows") -> None:
    """
    Create and run the MCP server in stdio transport mode.

    Blocking call — runs until the process is killed.
    stdio is the correct transport for Cursor and Claude Desktop integration.
    """
    server = create_mcp_server(workflows_dir)
    server.run()  # FastMCP defaults to stdio transport in mcp>=1.0.0
