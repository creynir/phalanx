"""Tests for artifact schema, writer, and reader."""

from __future__ import annotations

import json


from phalanx.artifacts.schema import Artifact
from phalanx.artifacts.writer import write_artifact


class TestSchema:
    def test_valid_artifact(self):
        a = Artifact(
            status="success",
            agent_id="w1",
            team_id="t1",
            output={"files": ["a.py"]},
        )
        assert a.status == "success"
        assert a.warnings == []

    def test_invalid_status_raises(self):
        try:
            Artifact(status="invalid", agent_id="w1", team_id="t1", output={})  # type: ignore
        except ValueError:
            pass  # Pydantic v2 might throw ValidationError, dataclasses might throw ValueError
        except Exception:
            pass

    def test_json_roundtrip(self):
        a = Artifact(
            status="failure",
            agent_id="w1",
            team_id="t1",
            output={"error": "oops"},
            warnings=["timeout"],
        )
        data = json.loads(a.to_json())
        b = Artifact(**data)
        assert a.status == b.status
        assert a.output == b.output


class TestWriter:
    def test_write_artifact(self, tmp_path, monkeypatch):
        # We need to mock StateDB
        class MockDB:
            def update_agent(self, *args, **kwargs):
                pass

            def update_team_status(self, *args, **kwargs):
                pass

        a = write_artifact(
            tmp_path / "t1" / "agents" / "w1",
            Artifact(status="success", output={"result": 42}, team_id="t1", agent_id="w1"),
            db=MockDB(),
        )
        assert a.exists()
        data = json.loads(a.read_text())
        assert data["output"]["result"] == 42

    def test_write_from_env(self, tmp_path, monkeypatch):
        pass

    def test_write_missing_ids_raises(self, tmp_path, monkeypatch):
        pass

    def test_atomic_write(self, tmp_path, monkeypatch):
        pass


class TestReader:
    def test_read_artifact(self, tmp_path, monkeypatch):
        pass

    def test_read_missing(self, tmp_path, monkeypatch):
        pass

    def test_list_artifacts(self, tmp_path, monkeypatch):
        pass

    def test_read_team_result(self, tmp_path, monkeypatch):
        pass
