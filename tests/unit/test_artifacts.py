"""Tests for artifact schema, writer, and reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phalanx.artifacts.schema import Artifact, ArtifactStatus
from phalanx.artifacts.writer import write_artifact, get_artifact_path
from phalanx.artifacts.reader import read_artifact, list_artifacts, read_team_result


class TestSchema:
    def test_valid_artifact(self):
        a = Artifact(
            status=ArtifactStatus.SUCCESS,
            agent_id="w1",
            team_id="t1",
            output={"files": ["a.py"]},
        )
        assert a.status == ArtifactStatus.SUCCESS
        assert a.warnings == []

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            Artifact(status="invalid", agent_id="w1", team_id="t1", output={})

    def test_json_roundtrip(self):
        a = Artifact(
            status=ArtifactStatus.FAILURE,
            agent_id="w1",
            team_id="t1",
            output={"error": "oops"},
            warnings=["timeout"],
        )
        data = json.loads(a.model_dump_json())
        b = Artifact(**data)
        assert a.status == b.status
        assert a.output == b.output


class TestWriter:
    def test_write_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.writer.TEAMS_DIR", tmp_path)
        a = write_artifact("success", {"result": 42}, team_id="t1", agent_id="w1")
        assert a.status == ArtifactStatus.SUCCESS
        path = get_artifact_path("t1", "w1")
        # path uses monkeypatched TEAMS_DIR so check via actual tmp
        actual = tmp_path / "t1" / "agents" / "w1" / "artifact.json"
        assert actual.exists()
        data = json.loads(actual.read_text())
        assert data["output"]["result"] == 42

    def test_write_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.writer.TEAMS_DIR", tmp_path)
        monkeypatch.setenv("PHALANX_TEAM_ID", "t2")
        monkeypatch.setenv("PHALANX_AGENT_ID", "w2")
        a = write_artifact("failure", {"reason": "crash"})
        assert a.team_id == "t2"
        assert a.agent_id == "w2"

    def test_write_missing_ids_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.writer.TEAMS_DIR", tmp_path)
        monkeypatch.delenv("PHALANX_TEAM_ID", raising=False)
        monkeypatch.delenv("PHALANX_AGENT_ID", raising=False)
        with pytest.raises(ValueError):
            write_artifact("success", {})

    def test_atomic_write(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.writer.TEAMS_DIR", tmp_path)
        write_artifact("success", {"v": 1}, team_id="t1", agent_id="w1")
        write_artifact("failure", {"v": 2}, team_id="t1", agent_id="w1")
        actual = tmp_path / "t1" / "agents" / "w1" / "artifact.json"
        data = json.loads(actual.read_text())
        assert data["status"] == "failure"
        assert data["output"]["v"] == 2


class TestReader:
    def test_read_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.writer.TEAMS_DIR", tmp_path)
        monkeypatch.setattr("phalanx.artifacts.reader.TEAMS_DIR", tmp_path)
        write_artifact("success", {"ok": True}, team_id="t1", agent_id="w1")
        a = read_artifact("t1", "w1")
        assert a is not None
        assert a.output["ok"] is True

    def test_read_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.reader.TEAMS_DIR", tmp_path)
        assert read_artifact("t1", "w99") is None

    def test_list_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.writer.TEAMS_DIR", tmp_path)
        monkeypatch.setattr("phalanx.artifacts.reader.TEAMS_DIR", tmp_path)
        write_artifact("success", {}, team_id="t1", agent_id="w1")
        write_artifact("failure", {}, team_id="t1", agent_id="w2")
        arts = list_artifacts("t1")
        assert len(arts) == 2

    def test_read_team_result(self, tmp_path, monkeypatch):
        monkeypatch.setattr("phalanx.artifacts.writer.TEAMS_DIR", tmp_path)
        monkeypatch.setattr("phalanx.artifacts.reader.TEAMS_DIR", tmp_path)
        write_artifact("success", {"summary": "done"}, team_id="t1", agent_id="lead-1")
        result = read_team_result("t1")
        assert result is not None
        assert result.output["summary"] == "done"
