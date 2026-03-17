"""Atomic artifact writer.

Agents call `phalanx write-artifact` which goes through this module
to ensure schema validity, atomic writes, and DB consistency.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from phalanx.artifacts.schema import Artifact


def write_artifact(
    artifact_dir: Path,
    artifact: Artifact,
    db=None,
) -> Path:
    """Atomically write an artifact to disk and update DB.

    Uses tmp-file + rename for crash safety.
    """
    errors = artifact.validate()
    if errors:
        raise ValueError(f"Invalid artifact: {'; '.join(errors)}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / "artifact.json"

    # Atomic write: write to temp, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(artifact_dir),
        suffix=".tmp",
        prefix="artifact_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(artifact.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, str(target))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Update DB if available — retry on SQLite lock contention
    if db and artifact.agent_id:
        for attempt in range(5):
            try:
                db.update_agent(
                    artifact.agent_id,
                    artifact_status=artifact.status,
                )
                break
            except Exception:
                if attempt < 4:
                    time.sleep(0.2 * (attempt + 1))

    return target
