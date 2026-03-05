"""
AC-18, AC-19: MCP server tool registration and return contract.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch
from phalanx.mcp_server import create_mcp_server


MINIMAL_WORKFLOW_YAML = """
version: "1.0"
blocks:
  review:
    type: linear
    soul_ref: reviewer
workflow:
  name: CodeReview
  entry: review
  transitions:
    - from: review
      to: null
"""


# AC-18
@pytest.mark.asyncio
async def test_tools_registered_per_workflow(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "code_review.yaml").write_text(MINIMAL_WORKFLOW_YAML)

    server = create_mcp_server(str(wf_dir))

    try:
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]
    except AttributeError:
        # Fallback for mcp SDK versions with different API
        tools = list(getattr(server, "_tool_manager", server)._tools.values())
        tool_names = [t.name for t in tools]

    assert any("code_review" in name.lower() or "codereview" in name.lower() for name in tool_names)


# AC-19
@pytest.mark.asyncio
async def test_mcp_tool_returns_json(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "simple.yaml").write_text("""
version: "1.0"
blocks:
  step1:
    type: linear
    soul_ref: generalist
workflow:
  name: Simple
  entry: step1
  transitions:
    - from: step1
      to: null
""")
    from phalanx_core.state import WorkflowState

    final_state = WorkflowState(
        results={"step1": "test output"},
        total_cost_usd=0.01,
        total_tokens=100,
    )
    final_state = final_state.model_copy(
        update={"messages": [{"role": "system", "content": "done"}]}
    )

    with patch(
        "phalanx_core.workflow.Workflow.run", new_callable=AsyncMock, return_value=final_state
    ):
        server = create_mcp_server(str(wf_dir))
        try:
            tools = await server.list_tools()
        except AttributeError:
            tools = list(getattr(server, "_tool_manager", server)._tools.values())
        assert len(tools) > 0
        tool = tools[0]
        result = await server.call_tool(
            tool.name, {"task_instruction": "test task", "task_context": ""}
        )

    # call_tool returns (content_blocks, metadata_dict)
    content_blocks, metadata = result
    # Extract the text from the first content block
    result_text = content_blocks[0].text if content_blocks else ""
    result_dict = json.loads(result_text)
    assert "results" in result_dict
    assert "messages_summary" in result_dict
    assert "cost_usd" in result_dict
    assert "total_tokens" in result_dict
    assert isinstance(result_dict["messages_summary"], int)
    assert isinstance(result_dict["cost_usd"], float)
    assert isinstance(result_dict["total_tokens"], int)
    assert result_dict["messages_summary"] == 1
    assert result_dict["cost_usd"] == pytest.approx(0.01)
    assert result_dict["total_tokens"] == 100


def test_empty_workflows_dir_creates_server_with_no_tools(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()

    server = create_mcp_server(str(wf_dir))
    assert server is not None


def test_nonexistent_workflows_dir_creates_server(tmp_path):
    server = create_mcp_server(str(tmp_path / "nonexistent"))
    assert server is not None
