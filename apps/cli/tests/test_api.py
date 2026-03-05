"""
Tests for FastAPI endpoints in the Phalanx API.

Tests the following endpoints:
- GET /api/workflows
- POST /api/workflows
- GET /api/workflows/{name}
- GET /api/tasks
- POST /api/tasks
- GET /api/tasks/{name}
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phalanx.api import app


@pytest.fixture
def temp_custom_base(monkeypatch):
    """Create a temporary directory for custom workflows and tasks.

    Patches the PHALANX_CUSTOM_BASE environment variable to use the temp directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("PHALANX_CUSTOM_BASE", tmpdir)
        yield Path(tmpdir)


@pytest.fixture
def client(temp_custom_base):
    """Create a TestClient for the FastAPI app."""
    return TestClient(app)


class TestWorkflowsEndpoints:
    """Tests for workflow endpoints."""

    def test_get_workflows_empty(self, client):
        """Test GET /api/workflows returns empty list when no workflows exist."""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        assert response.json() == []

    def test_post_workflow_and_get(self, client):
        """Test POST /api/workflows creates a workflow and GET returns it."""
        # Create a workflow
        workflow_yaml = "version: '1.0'\nblocks: {}"
        response = client.post("/api/workflows", json={"content": workflow_yaml})
        assert response.status_code == 200
        workflow_data = response.json()
        assert "id" in workflow_data
        workflow_id = workflow_data["id"]

        # Verify it appears in the list
        response = client.get("/api/workflows")
        assert response.status_code == 200
        workflows = response.json()
        assert len(workflows) == 1
        assert workflows[0]["name"] == workflow_id

    def test_get_nonexistent_workflow(self, client):
        """Test GET /api/workflows/{nonexistent} returns 404."""
        response = client.get("/api/workflows/nonexistent")
        assert response.status_code == 404


class TestTasksEndpoints:
    """Tests for task endpoints."""

    def test_get_tasks_empty(self, client):
        """Test GET /api/tasks returns empty list when no tasks exist."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_post_task_and_get(self, client):
        """Test POST /api/tasks creates a task and GET returns it."""
        # Create a task
        task_yaml = "version: '1.0'\nsteps: []"
        response = client.post("/api/tasks", json={"content": task_yaml})
        assert response.status_code == 200
        task_data = response.json()
        assert "id" in task_data
        task_id = task_data["id"]

        # Verify it appears in the list
        response = client.get("/api/tasks")
        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["name"] == task_id
