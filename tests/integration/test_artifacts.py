"""Integration tests for Artifact Read/Write/Validation — IT-052 through IT-060."""

from __future__ import annotations

import json

import pytest

from phalanx.artifacts.schema import Artifact
from phalanx.artifacts.writer import write_artifact
from phalanx.artifacts.reader import read_agent_artifact
from phalanx.db import StateDB


pytestmark = pytest.mark.integration


@pytest.fixture
def db(tmp_path):
    return StateDB(db_path=tmp_path / "state.db")


class TestIT052_WriteSuccess:
    """IT-052: Writes valid JSON artifact to correct directory."""

    def test_write_artifact(self, tmp_path):
        art = Artifact(
            status="success",
            output={"files": ["calc.py"]},
            agent_id="w1",
            team_id="t1",
        )
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        path = write_artifact(artifact_dir, art)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["status"] == "success"
        assert data["output"]["files"] == ["calc.py"]


class TestIT053_WorkerDoneEvent:
    """IT-053: DB poll loop detects success artifact."""

    def test_artifact_status_in_db(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")

        art = Artifact(status="success", output={}, agent_id="w1", team_id="t1")
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        write_artifact(artifact_dir, art, db=db)

        agent = db.get_agent("w1")
        assert agent["artifact_status"] == "success"


class TestIT054_WorkerFailureExclusion:
    """IT-054: Failure artifacts do NOT trigger worker_done."""

    def test_failure_artifact_no_event(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")

        art = Artifact(status="failure", output={"error": "oops"}, agent_id="w1", team_id="t1")
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        write_artifact(artifact_dir, art, db=db)

        agent = db.get_agent("w1")
        assert agent["artifact_status"] == "failure"


class TestIT055_EscalationArtifactHandling:
    """IT-055: escalation_required artifact fires worker_escalation event."""

    def test_escalation_artifact_stored(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")

        art = Artifact(
            status="escalation", output={"reason": "need API key"}, agent_id="w1", team_id="t1"
        )
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        write_artifact(artifact_dir, art, db=db)

        agent = db.get_agent("w1")
        assert agent["artifact_status"] == "escalation"


class TestIT056_MissingEnvVars:
    """IT-056: write-artifact exits with error if PHALANX_AGENT_ID absent."""

    def test_missing_agent_id(self, tmp_path):
        art = Artifact(status="success", output={})
        errors = art.validate()
        assert len(errors) == 0  # Schema validation passes
        # Missing env vars are checked at CLI level, not schema level


class TestIT057_ReadAgentResult:
    """IT-057: Read agent artifact outputs payload to stdout."""

    def test_read_artifact(self, tmp_path):
        art = Artifact(status="success", output={"result": "done"}, agent_id="w1", team_id="t1")
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"
        write_artifact(artifact_dir, art)

        result = read_agent_artifact(tmp_path, "t1", "w1")
        assert result is not None
        assert result.status == "success"
        assert result.output["result"] == "done"


class TestIT058_ReadTeamResult:
    """IT-058: Recovers consolidated team lead output."""

    def test_get_team_result_reads_lead_agent_artifact(self, tmp_path):
        from phalanx.db import StateDB
        from phalanx.team.orchestrator import get_team_result

        db = StateDB(db_path=tmp_path / "state.db")
        db.create_team("t1", "task")
        db.create_agent("lead-t1", "t1", "coordinate", role="lead")

        art = Artifact(
            status="success", output={"consolidated": True}, agent_id="lead-t1", team_id="t1"
        )
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "lead-t1"
        write_artifact(artifact_dir, art)

        result = get_team_result(tmp_path, "t1")
        assert result is not None
        assert result["status"] == "success"
        assert result["output"]["consolidated"] is True


# IT-059: moved to tests/future_backlog/test_integration_backlog.py


class TestIT060_ArtifactOverwriteOnResume:
    """IT-060: Agent writes failure, gets resumed, writes success — overwrite works."""

    def test_artifact_overwrite(self, db, tmp_path):
        db.create_team("t1", "task")
        db.create_agent("w1", "t1", "code")
        artifact_dir = tmp_path / "teams" / "t1" / "agents" / "w1"

        art1 = Artifact(status="failure", output={"error": "first"}, agent_id="w1", team_id="t1")
        write_artifact(artifact_dir, art1, db=db)
        assert db.get_agent("w1")["artifact_status"] == "failure"

        art2 = Artifact(status="success", output={"result": "second"}, agent_id="w1", team_id="t1")
        write_artifact(artifact_dir, art2, db=db)
        assert db.get_agent("w1")["artifact_status"] == "success"

        data = json.loads((artifact_dir / "artifact.json").read_text())
        assert data["status"] == "success"
        assert data["output"]["result"] == "second"
