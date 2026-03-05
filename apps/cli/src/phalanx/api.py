"""
FastAPI application for managing workflows and tasks.

Provides REST endpoints for listing, creating, and retrieving workflows and tasks.
Workflows and tasks are stored as YAML files in custom/workflows/ and custom/tasks/.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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

    Args:
        body: Request body with 'content' field containing YAML

    Returns:
        Dictionary with the generated workflow ID
    """
    workflow_id = str(uuid.uuid4())
    _write_item("workflows", workflow_id, body.content)
    return {"id": workflow_id}


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
