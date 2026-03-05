"""Tests for the FastAPI application (api.py).

Covers all acceptance criteria:
- GET /api/workflows returns a list of workflow names
- POST /api/workflows accepts YAML and saves to custom/workflows/{id}.yaml
- GET /api/actions returns a list of action names
- POST /api/actions accepts YAML and saves to custom/actions/{id}.yaml
- GET /api/workflows/{name} and GET /api/actions/{name} return file contents
- Missing directories are created automatically
- 404 is returned for missing files
"""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from phalanx.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client and set the custom base directory."""
    monkeypatch.setenv("PHALANX_CUSTOM_BASE", str(tmp_path / "custom"))
    # Also need to reload the app's import to pick up the env var
    # We'll patch the function directly instead
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
        (custom_dir / "workflow1.yaml").write_text("version: '1.0'")
        (custom_dir / "workflow2.yaml").write_text("version: '1.0'")

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
        (custom_dir / "z_workflow.yaml").write_text("version: '1.0'")
        (custom_dir / "a_workflow.yaml").write_text("version: '1.0'")
        (custom_dir / "m_workflow.yaml").write_text("version: '1.0'")

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

        response = client.post(
            "/api/workflows", json={"content": "version: '1.0'\nname: MyWorkflow"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert custom_dir.exists()

    def test_create_workflow_writes_file(self, client, tmp_path):
        """Test that POST /api/workflows writes the YAML file."""
        yaml_content = "version: '1.0'\nname: TestWorkflow"
        response = client.post("/api/workflows", json={"content": yaml_content})
        assert response.status_code == 200
        data = response.json()
        workflow_id = data["id"]

        file_path = tmp_path / "custom" / "workflows" / f"{workflow_id}.yaml"
        assert file_path.exists()
        assert file_path.read_text() == yaml_content

    def test_create_workflow_generates_unique_id(self, client):
        """Test that each workflow gets a unique ID."""
        yaml_content = "version: '1.0'"
        response1 = client.post("/api/workflows", json={"content": yaml_content})
        response2 = client.post("/api/workflows", json={"content": yaml_content})

        id1 = response1.json()["id"]
        id2 = response2.json()["id"]
        assert id1 != id2


class TestGetWorkflow:
    """Test GET /api/workflows/{name} endpoint."""

    def test_get_workflow_success(self, client, tmp_path):
        """Test retrieving an existing workflow."""
        custom_dir = tmp_path / "custom" / "workflows"
        custom_dir.mkdir(parents=True, exist_ok=True)
        yaml_content = "version: '1.0'\nname: MyWorkflow"
        (custom_dir / "test_wf.yaml").write_text(yaml_content)

        response = client.get("/api/workflows/test_wf")
        assert response.status_code == 200
        assert response.json() == {"content": yaml_content}

    def test_get_workflow_not_found(self, client):
        """Test that 404 is returned for missing workflow."""
        response = client.get("/api/workflows/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "workflow not found" in data["detail"].lower()

    def test_get_workflow_with_uuid(self, client, tmp_path):
        """Test retrieving a workflow by UUID."""
        yaml_content = "version: '1.0'"
        response = client.post("/api/workflows", json={"content": yaml_content})
        workflow_id = response.json()["id"]

        response = client.get(f"/api/workflows/{workflow_id}")
        assert response.status_code == 200
        assert response.json()["content"] == yaml_content


class TestListActions:
    """Test GET /api/actions endpoint."""

    def test_list_actions_empty(self, client):
        """Test listing actions when none exist."""
        response = client.get("/api/actions")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_actions_with_items(self, client, tmp_path):
        """Test listing actions when some exist."""
        custom_dir = tmp_path / "custom" / "actions"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "action1.yaml").write_text("version: '1.0'")
        (custom_dir / "action2.yaml").write_text("version: '1.0'")

        response = client.get("/api/actions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [item["name"] for item in data]
        assert sorted(names) == ["action1", "action2"]

    def test_list_actions_sorted(self, client, tmp_path):
        """Test that actions are returned in sorted order."""
        custom_dir = tmp_path / "custom" / "actions"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "z_action.yaml").write_text("version: '1.0'")
        (custom_dir / "a_action.yaml").write_text("version: '1.0'")
        (custom_dir / "m_action.yaml").write_text("version: '1.0'")

        response = client.get("/api/actions")
        assert response.status_code == 200
        data = response.json()
        names = [item["name"] for item in data]
        assert names == ["a_action", "m_action", "z_action"]


class TestCreateAction:
    """Test POST /api/actions endpoint."""

    def test_create_action_auto_creates_directory(self, client, tmp_path):
        """Test that POST /api/actions creates the directory if it doesn't exist."""
        custom_dir = tmp_path / "custom" / "actions"
        assert not custom_dir.exists()

        response = client.post("/api/actions", json={"content": "version: '1.0'\nname: MyAction"})
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert custom_dir.exists()

    def test_create_action_writes_file(self, client, tmp_path):
        """Test that POST /api/actions writes the YAML file."""
        yaml_content = "version: '1.0'\nname: TestAction"
        response = client.post("/api/actions", json={"content": yaml_content})
        assert response.status_code == 200
        data = response.json()
        action_id = data["id"]

        file_path = tmp_path / "custom" / "actions" / f"{action_id}.yaml"
        assert file_path.exists()
        assert file_path.read_text() == yaml_content

    def test_create_action_generates_unique_id(self, client):
        """Test that each action gets a unique ID."""
        yaml_content = "version: '1.0'"
        response1 = client.post("/api/actions", json={"content": yaml_content})
        response2 = client.post("/api/actions", json={"content": yaml_content})

        id1 = response1.json()["id"]
        id2 = response2.json()["id"]
        assert id1 != id2


class TestGetAction:
    """Test GET /api/actions/{name} endpoint."""

    def test_get_action_success(self, client, tmp_path):
        """Test retrieving an existing action."""
        custom_dir = tmp_path / "custom" / "actions"
        custom_dir.mkdir(parents=True, exist_ok=True)
        yaml_content = "version: '1.0'\nname: MyAction"
        (custom_dir / "test_action.yaml").write_text(yaml_content)

        response = client.get("/api/actions/test_action")
        assert response.status_code == 200
        assert response.json() == {"content": yaml_content}

    def test_get_action_not_found(self, client):
        """Test that 404 is returned for missing action."""
        response = client.get("/api/actions/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "action not found" in data["detail"].lower()

    def test_get_action_with_uuid(self, client, tmp_path):
        """Test retrieving an action by UUID."""
        yaml_content = "version: '1.0'"
        response = client.post("/api/actions", json={"content": yaml_content})
        action_id = response.json()["id"]

        response = client.get(f"/api/actions/{action_id}")
        assert response.status_code == 200
        assert response.json()["content"] == yaml_content


class TestIntegration:
    """Integration tests combining multiple endpoints."""

    def test_workflow_lifecycle(self, client, tmp_path):
        """Test complete workflow lifecycle: create, list, retrieve."""
        # Create a workflow
        yaml_content = "version: '1.0'\nname: Integration"
        response = client.post("/api/workflows", json={"content": yaml_content})
        assert response.status_code == 200
        workflow_id = response.json()["id"]

        # List workflows
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == workflow_id

        # Retrieve the workflow
        response = client.get(f"/api/workflows/{workflow_id}")
        assert response.status_code == 200
        assert response.json()["content"] == yaml_content

    def test_action_lifecycle(self, client, tmp_path):
        """Test complete action lifecycle: create, list, retrieve."""
        # Create an action
        yaml_content = "version: '1.0'\nname: IntegrationAction"
        response = client.post("/api/actions", json={"content": yaml_content})
        assert response.status_code == 200
        action_id = response.json()["id"]

        # List actions
        response = client.get("/api/actions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == action_id

        # Retrieve the action
        response = client.get(f"/api/actions/{action_id}")
        assert response.status_code == 200
        assert response.json()["content"] == yaml_content

    def test_workflows_and_actions_independent(self, client):
        """Test that workflows and actions are independent."""
        # Create a workflow and an action
        wf_content = "version: '1.0'\nname: WF"
        action_content = "version: '1.0'\nname: Action"

        wf_response = client.post("/api/workflows", json={"content": wf_content})
        action_response = client.post("/api/actions", json={"content": action_content})

        wf_id = wf_response.json()["id"]
        action_id = action_response.json()["id"]

        # Listing workflows should not include actions
        wf_list = client.get("/api/workflows").json()
        assert len(wf_list) == 1
        assert wf_list[0]["name"] == wf_id

        # Listing actions should not include workflows
        action_list = client.get("/api/actions").json()
        assert len(action_list) == 1
        assert action_list[0]["name"] == action_id

    def test_multiple_workflows_and_actions(self, client):
        """Test creating and listing multiple workflows and actions."""
        # Create multiple workflows
        for i in range(3):
            client.post("/api/workflows", json={"content": f"workflow_{i}"})

        # Create multiple actions
        for i in range(2):
            client.post("/api/actions", json={"content": f"action_{i}"})

        # Verify counts
        wf_list = client.get("/api/workflows").json()
        action_list = client.get("/api/actions").json()

        assert len(wf_list) == 3
        assert len(action_list) == 2
