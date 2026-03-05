"""
FastAPI application for managing workflows and tasks.

Provides REST endpoints for listing, creating, and retrieving workflows and tasks.
Workflows and tasks are stored as YAML files in custom/workflows/ and custom/tasks/.
"""

from __future__ import annotations

import logging
import uuid
import yaml
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from phalanx_core.primitives import Task
from phalanx_core.state import WorkflowState
from phalanx_core.yaml.parser import parse_workflow_yaml
from phalanx_core.yaml.schema import PhalanxWorkflowFile

logger = logging.getLogger(__name__)

# Create the FastAPI app instance
app = FastAPI(title="Phalanx API", version="1.0.0")

# Default base directory for custom workflows and tasks
DEFAULT_CUSTOM_BASE = Path("custom")


class YAMLContent(BaseModel):
    """Request body for YAML content."""

    content: str


class ItemInfo(BaseModel):
    """Information about a workflow or task."""

    name: str


class RunWorkflowTask(BaseModel):
    """Task definition for POST /api/workflows/{id}/run."""

    id: str = Field(..., description="Unique identifier for the task")
    instruction: str = Field(..., description="The main instruction or prompt for the task")
    context: Optional[str] = Field(default=None, description="Additional context for the task")


def _get_base_dir() -> Path:
    """Get the base directory for custom files.

    Can be overridden by setting the PHALANX_CUSTOM_BASE environment variable.
    """
    import os

    custom_base = os.getenv("PHALANX_CUSTOM_BASE", str(DEFAULT_CUSTOM_BASE))
    return Path(custom_base)


def _list_items(item_type: str) -> list[str]:
    """List all item names (workflow or task) in the custom directory.

    Args:
        item_type: Either "workflows" or "tasks"

    Returns:
        List of item names (without .yaml extension)
    """
    base = _get_base_dir()
    item_dir = base / item_type

    if not item_dir.exists():
        return []

    items = []
    for yaml_file in sorted(item_dir.glob("*.yaml")):
        items.append(yaml_file.stem)

    return items


def _get_item_path(item_type: str, name: str) -> Path:
    """Get the full path to an item file.

    Args:
        item_type: Either "workflows" or "tasks"
        name: The item name (without extension)

    Returns:
        The Path to the item file
    """
    base = _get_base_dir()
    return base / item_type / f"{name}.yaml"


def _read_item(item_type: str, name: str) -> str:
    """Read the contents of a workflow or task file.

    Args:
        item_type: Either "workflows" or "tasks"
        name: The item name (without extension)

    Returns:
        The file contents

    Raises:
        HTTPException: If the file does not exist
    """
    item_path = _get_item_path(item_type, name)

    if not item_path.exists():
        raise HTTPException(status_code=404, detail=f"{item_type.rstrip('s')} not found")

    return item_path.read_text(encoding="utf-8")


def _write_item(item_type: str, name: str, content: str) -> None:
    """Write YAML content to a workflow or task file.

    Creates the directory if it doesn't exist.

    Args:
        item_type: Either "workflows" or "tasks"
        name: The item name (without extension)
        content: The YAML content to write
    """
    base = _get_base_dir()
    item_dir = base / item_type

    # Create directory if needed
    item_dir.mkdir(parents=True, exist_ok=True)

    item_path = item_dir / f"{name}.yaml"
    item_path.write_text(content, encoding="utf-8")


# Workflows endpoints


@app.get("/api/workflows", response_model=list[ItemInfo])
def list_workflows() -> list[ItemInfo]:
    """Get a list of all workflows.

    Returns:
        List of workflow names
    """
    names = _list_items("workflows")
    return [ItemInfo(name=name) for name in names]


@app.post("/api/workflows", response_model=dict[str, Any])
def create_workflow(body: YAMLContent) -> dict[str, Any]:
    """Create a new workflow from YAML content.

    Generates a unique ID for the workflow and saves it to custom/workflows/{id}.yaml.
    Validates the YAML against PhalanxWorkflowFile schema before saving.

    Args:
        body: Request body with 'content' field containing YAML

    Returns:
        Dictionary with the generated workflow ID

    Raises:
        HTTPException: 400 if YAML is invalid or fails schema validation
    """
    try:
        raw = yaml.safe_load(body.content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=400,
            detail={"message": "Invalid YAML", "errors": [str(e)]},
        ) from e
    if raw is None:
        raise HTTPException(
            status_code=400,
            detail={"message": "Empty or invalid YAML", "errors": ["Document is empty"]},
        )
    try:
        PhalanxWorkflowFile.model_validate(raw)
    except PydanticValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={"message": "Workflow validation failed", "errors": e.errors()},
        ) from e
    workflow_id = str(uuid.uuid4())
    _write_item("workflows", workflow_id, body.content)
    return {"id": workflow_id}


@app.post("/api/workflows/{workflow_id}/run", response_model=dict[str, Any])
async def run_workflow(workflow_id: str, task: RunWorkflowTask) -> dict[str, Any]:
    """Execute a workflow with the given task.

    Reads the workflow YAML from disk, parses it, creates an initial WorkflowState
    with the provided Task, and runs the workflow. Returns a summary of the result.

    Args:
        workflow_id: The workflow ID (without .yaml extension)
        task: JSON body with id, instruction, and optional context

    Returns:
        Summary dict with results, total_cost_usd, and total_tokens

    Raises:
        HTTPException: 404 if workflow not found; 400/500 on parse or execution errors
    """
    content = _read_item("workflows", workflow_id)
    try:
        workflow = parse_workflow_yaml(content)
    except Exception as e:
        logger.exception("Failed to parse workflow %s", workflow_id)
        raise HTTPException(
            status_code=400,
            detail={"message": "Failed to parse workflow", "errors": [str(e)]},
        ) from e
    phalanx_task = Task(
        id=task.id,
        instruction=task.instruction,
        context=task.context,
    )
    initial_state = WorkflowState(current_task=phalanx_task)
    try:
        final_state = await workflow.run(initial_state=initial_state)
    except Exception as e:
        logger.exception("Workflow %s execution failed", workflow_id)
        raise HTTPException(
            status_code=500,
            detail={"message": "Workflow execution failed", "errors": [str(e)]},
        ) from e
    return {
        "results": final_state.results,
        "total_cost_usd": final_state.total_cost_usd,
        "total_tokens": final_state.total_tokens,
    }


@app.get("/api/workflows/{name}")
def get_workflow(name: str) -> dict[str, str]:
    """Get the contents of a specific workflow.

    Args:
        name: The workflow name/ID (without .yaml extension)

    Returns:
        Dictionary with 'content' field containing the YAML

    Raises:
        HTTPException: 404 if the workflow does not exist
    """
    content = _read_item("workflows", name)
    return {"content": content}


# Tasks endpoints


@app.get("/api/tasks", response_model=list[ItemInfo])
def list_tasks() -> list[ItemInfo]:
    """Get a list of all tasks.

    Returns:
        List of task names
    """
    names = _list_items("tasks")
    return [ItemInfo(name=name) for name in names]


@app.post("/api/tasks", response_model=dict[str, Any])
def create_task(body: YAMLContent) -> dict[str, Any]:
    """Create a new task from YAML content.

    Generates a unique ID for the task and saves it to custom/tasks/{id}.yaml.

    Args:
        body: Request body with 'content' field containing YAML

    Returns:
        Dictionary with the generated task ID
    """
    task_id = str(uuid.uuid4())
    _write_item("tasks", task_id, body.content)
    return {"id": task_id}


@app.get("/api/tasks/{name}")
def get_task(name: str) -> dict[str, str]:
    """Get the contents of a specific task.

    Args:
        name: The task name/ID (without .yaml extension)

    Returns:
        Dictionary with 'content' field containing the YAML

    Raises:
        HTTPException: 404 if the task does not exist
    """
    content = _read_item("tasks", name)
    return {"content": content}
