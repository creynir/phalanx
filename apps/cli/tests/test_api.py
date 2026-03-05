"""
Tests for the FastAPI application (api.py).

Covers:
- GET /api/workflows, POST /api/workflows, GET /api/workflows/{name}
- POST /api/workflows validation (400 on invalid YAML)
- POST /api/workflows/{id}/run (mocked)
- GET /api/tasks, POST /api/tasks, GET /api/tasks/{name}
- Missing directories created automatically
- 404 for missing files
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from phalanx.api import app


VALID_WORKFLOW_YAML = """
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


def _valid_workflow_yaml(name: str = "TestWorkflow", block_id: str = "review") -> str:
    """Generate valid workflow YAML with custom name/block_id."""
    return f"""
version: "1.0"
blocks:
  {block_id}:
    type: linear
    soul_ref: reviewer
workflow:
  name: {name}
  entry: {block_id}
  transitions:
    - from: {block_id}
      to: null
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client and set the custom base directory."""
    monkeypatch.setenv("PHALANX_CUSTOM_BASE", str(tmp_path / "custom"))
    from phalanx import api

    original_get_base_dir = api._get_base_dir

    def patched_get_base_dir():
        return tmp_path / "custom"

    api._get_base_dir = patched_get_base_dir
    yield TestClient(app)
    api._get_base_dir = original_get_base_dir


class TestListWorkflows:
    """Test GET /api/workflows endpoint."""

    def test_list_workflows_empty(self, client):
        """Test listing workflows when none exist."""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_workflows_with_items(self, client, tmp_path):
        """Test listing workflows when some exist."""
        custom_dir = tmp_path / "custom" / "workflows"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "workflow1.yaml").write_text(VALID_WORKFLOW_YAML)
        (custom_dir / "workflow2.yaml").write_text(VALID_WORKFLOW_YAML)

        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [item["name"] for item in data]
        assert sorted(names) == ["workflow1", "workflow2"]

    def test_list_workflows_sorted(self, client, tmp_path):
        """Test that workflows are returned in sorted order."""
        custom_dir = tmp_path / "custom" / "workflows"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "z_workflow.yaml").write_text(VALID_WORKFLOW_YAML)
        (custom_dir / "a_workflow.yaml").write_text(VALID_WORKFLOW_YAML)
        (custom_dir / "m_workflow.yaml").write_text(VALID_WORKFLOW_YAML)

        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        names = [item["name"] for item in data]
        assert names == ["a_workflow", "m_workflow", "z_workflow"]


class TestCreateWorkflow:
    """Test POST /api/workflows endpoint."""

    def test_create_workflow_auto_creates_directory(self, client, tmp_path):
        """Test that POST /api/workflows creates the directory if it doesn't exist."""
        custom_dir = tmp_path / "custom" / "workflows"
        assert not custom_dir.exists()

        response = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert custom_dir.exists()

    def test_create_workflow_writes_file(self, client, tmp_path):
        """Test that POST /api/workflows writes the YAML file."""
        response = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})
        assert response.status_code == 200
        data = response.json()
        workflow_id = data["id"]

        file_path = tmp_path / "custom" / "workflows" / f"{workflow_id}.yaml"
        assert file_path.exists()
        assert file_path.read_text() == VALID_WORKFLOW_YAML

    def test_create_workflow_generates_unique_id(self, client):
        """Test that each workflow gets a unique ID."""
        response1 = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})
        response2 = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})

        id1 = response1.json()["id"]
        id2 = response2.json()["id"]
        assert id1 != id2

    def test_create_workflow_invalid_yaml_returns_400(self, client):
        """Test that POST /api/workflows returns 400 on syntactically invalid YAML."""
        response = client.post(
            "/api/workflows",
            json={"content": "not: valid: yaml: [[["},
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        detail = data["detail"]
        assert "message" in detail or "errors" in detail

    def test_create_workflow_invalid_schema_returns_400(self, client):
        """Test that POST /api/workflows returns 400 when YAML fails PhalanxWorkflowFile validation."""
        # Missing required 'workflow' key
        response = client.post(
            "/api/workflows",
            json={"content": "version: '1.0'\nname: OnlyTopLevel"},
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        detail = data["detail"]
        assert "errors" in detail


class TestGetWorkflow:
    """Test GET /api/workflows/{name} endpoint."""

    def test_get_workflow_success(self, client, tmp_path):
        """Test retrieving an existing workflow."""
        custom_dir = tmp_path / "custom" / "workflows"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "test_wf.yaml").write_text(VALID_WORKFLOW_YAML)

        response = client.get("/api/workflows/test_wf")
        assert response.status_code == 200
        assert response.json() == {"content": VALID_WORKFLOW_YAML}

    def test_get_workflow_not_found(self, client):
        """Test that 404 is returned for missing workflow."""
        response = client.get("/api/workflows/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "workflow not found" in str(data.get("detail", "")).lower()

    def test_get_workflow_with_uuid(self, client):
        """Test retrieving a workflow by UUID."""
        response = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})
        workflow_id = response.json()["id"]

        response = client.get(f"/api/workflows/{workflow_id}")
        assert response.status_code == 200
        assert response.json()["content"] == VALID_WORKFLOW_YAML


class TestRunWorkflow:
    """Test POST /api/workflows/{id}/run endpoint."""

    def test_run_workflow_returns_summary(self, client):
        """Test that POST /api/workflows/{id}/run returns results, total_cost_usd, total_tokens."""
        from phalanx_core.state import WorkflowState

        # Create a workflow first
        response = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})
        assert response.status_code == 200
        workflow_id = response.json()["id"]

        final_state = WorkflowState(
            results={"review": "test output"},
            total_cost_usd=0.02,
            total_tokens=200,
        )
        with patch(
            "phalanx_core.workflow.Workflow.run",
            new_callable=AsyncMock,
            return_value=final_state,
        ):
            response = client.post(
                f"/api/workflows/{workflow_id}/run",
                json={
                    "id": "task1",
                    "instruction": "Review this code",
                    "context": "Optional context",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert data["results"] == {"review": "test output"}
        assert data["total_cost_usd"] == 0.02
        assert data["total_tokens"] == 200

    def test_run_workflow_not_found_returns_404(self, client):
        """Test that run returns 404 when workflow does not exist."""
        response = client.post(
            "/api/workflows/nonexistent-id/run",
            json={"id": "t1", "instruction": "Do something"},
        )
        assert response.status_code == 404


class TestListTasks:
    """Test GET /api/tasks endpoint."""

    def test_list_tasks_empty(self, client):
        """Test listing tasks when none exist."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_tasks_with_items(self, client, tmp_path):
        """Test listing tasks when some exist."""
        custom_dir = tmp_path / "custom" / "tasks"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "task1.yaml").write_text("version: '1.0'")
        (custom_dir / "task2.yaml").write_text("version: '1.0'")

        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [item["name"] for item in data]
        assert sorted(names) == ["task1", "task2"]

    def test_list_tasks_sorted(self, client, tmp_path):
        """Test that tasks are returned in sorted order."""
        custom_dir = tmp_path / "custom" / "tasks"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "z_task.yaml").write_text("version: '1.0'")
        (custom_dir / "a_task.yaml").write_text("version: '1.0'")
        (custom_dir / "m_task.yaml").write_text("version: '1.0'")

        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        names = [item["name"] for item in data]
        assert names == ["a_task", "m_task", "z_task"]


class TestCreateTask:
    """Test POST /api/tasks endpoint."""

    def test_create_task_auto_creates_directory(self, client, tmp_path):
        """Test that POST /api/tasks creates the directory if it doesn't exist."""
        custom_dir = tmp_path / "custom" / "tasks"
        assert not custom_dir.exists()

        response = client.post("/api/tasks", json={"content": "version: '1.0'\nname: MyTask"})
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert custom_dir.exists()

    def test_create_task_writes_file(self, client, tmp_path):
        """Test that POST /api/tasks writes the YAML file."""
        yaml_content = "version: '1.0'\nname: TestTask"
        response = client.post("/api/tasks", json={"content": yaml_content})
        assert response.status_code == 200
        data = response.json()
        task_id = data["id"]

        file_path = tmp_path / "custom" / "tasks" / f"{task_id}.yaml"
        assert file_path.exists()
        assert file_path.read_text() == yaml_content

    def test_create_task_generates_unique_id(self, client):
        """Test that each task gets a unique ID."""
        yaml_content = "version: '1.0'"
        response1 = client.post("/api/tasks", json={"content": yaml_content})
        response2 = client.post("/api/tasks", json={"content": yaml_content})

        id1 = response1.json()["id"]
        id2 = response2.json()["id"]
        assert id1 != id2


class TestGetTask:
    """Test GET /api/tasks/{name} endpoint."""

    def test_get_task_success(self, client, tmp_path):
        """Test retrieving an existing task."""
        custom_dir = tmp_path / "custom" / "tasks"
        custom_dir.mkdir(parents=True, exist_ok=True)
        yaml_content = "version: '1.0'\nname: MyTask"
        (custom_dir / "test_task.yaml").write_text(yaml_content)

        response = client.get("/api/tasks/test_task")
        assert response.status_code == 200
        assert response.json() == {"content": yaml_content}

    def test_get_task_not_found(self, client):
        """Test that 404 is returned for missing task."""
        response = client.get("/api/tasks/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "task not found" in str(data.get("detail", "")).lower()

    def test_get_task_with_uuid(self, client):
        """Test retrieving a task by UUID."""
        yaml_content = "version: '1.0'"
        response = client.post("/api/tasks", json={"content": yaml_content})
        task_id = response.json()["id"]

        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["content"] == yaml_content


class TestIntegration:
    """Integration tests combining multiple endpoints."""

    def test_workflow_lifecycle(self, client):
        """Test complete workflow lifecycle: create, list, retrieve."""
        response = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})
        assert response.status_code == 200
        workflow_id = response.json()["id"]

        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == workflow_id

        response = client.get(f"/api/workflows/{workflow_id}")
        assert response.status_code == 200
        assert response.json()["content"] == VALID_WORKFLOW_YAML

    def test_task_lifecycle(self, client):
        """Test complete task lifecycle: create, list, retrieve."""
        yaml_content = "version: '1.0'\nname: IntegrationTask"
        response = client.post("/api/tasks", json={"content": yaml_content})
        assert response.status_code == 200
        task_id = response.json()["id"]

        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == task_id

        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["content"] == yaml_content

    def test_workflows_and_tasks_independent(self, client):
        """Test that workflows and tasks are independent."""
        wf_response = client.post("/api/workflows", json={"content": VALID_WORKFLOW_YAML})
        task_response = client.post("/api/tasks", json={"content": "version: '1.0'\nname: Task"})

        wf_id = wf_response.json()["id"]
        task_id = task_response.json()["id"]

        wf_list = client.get("/api/workflows").json()
        assert len(wf_list) == 1
        assert wf_list[0]["name"] == wf_id

        task_list = client.get("/api/tasks").json()
        assert len(task_list) == 1
        assert task_list[0]["name"] == task_id

    def test_multiple_workflows_and_tasks(self, client):
        """Test creating and listing multiple workflows and tasks."""
        for i in range(3):
            client.post(
                "/api/workflows",
                json={"content": _valid_workflow_yaml(name=f"WF{i}", block_id="step")},
            )

        for i in range(2):
            client.post(
                "/api/tasks",
                json={"content": f"version: '1.0'\nname: task_{i}"},
            )

        wf_list = client.get("/api/workflows").json()
        task_list = client.get("/api/tasks").json()

        assert len(wf_list) == 3
        assert len(task_list) == 2
