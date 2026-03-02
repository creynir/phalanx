"""SQLite state management with WAL mode.

All phalanx state lives in a single SQLite database (.phalanx/state.db).
WAL mode enables concurrent reads during writes. Busy timeout handles
contention from multiple agents.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id          TEXT PRIMARY KEY,
    task        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    config      TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    team_id         TEXT NOT NULL REFERENCES teams(id),
    role            TEXT NOT NULL DEFAULT 'worker',
    task            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    pid             INTEGER,
    chat_id         TEXT,
    worktree        TEXT,
    model           TEXT,
    backend         TEXT DEFAULT 'cursor',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    artifact_status TEXT,
    last_heartbeat  REAL,
    attempts        INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    stall_seconds   INTEGER DEFAULT 1800,
    max_runtime     INTEGER DEFAULT 1800,
    prompt_state    TEXT,
    prompt_screen   TEXT
);

CREATE TABLE IF NOT EXISTS feed (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     TEXT NOT NULL REFERENCES teams(id),
    sender_id   TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS file_locks (
    file_path   TEXT PRIMARY KEY,
    team_id     TEXT NOT NULL REFERENCES teams(id),
    agent_id    TEXT NOT NULL,
    pid         INTEGER NOT NULL,
    locked_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     TEXT NOT NULL,
    agent_id    TEXT,
    event_type  TEXT NOT NULL,
    payload     TEXT,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


class StateDB:
    """Thread-safe SQLite state database."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._path),
            timeout=5.0,
            isolation_level="DEFERRED",
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            existing_tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            if "schema_version" in existing_tables:
                row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if row and row["version"] < SCHEMA_VERSION:
                    self._migrate(conn, row["version"])

            conn.executescript(_SCHEMA)

            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )

    def _migrate(self, conn: sqlite3.Connection, from_version: int) -> None:
        """Run incremental migrations from from_version to SCHEMA_VERSION."""
        if from_version < 3:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "messages" in tables and "feed" not in tables:
                conn.execute(
                    "CREATE TABLE feed ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "team_id TEXT NOT NULL REFERENCES teams(id), "
                    "sender_id TEXT NOT NULL, "
                    "content TEXT NOT NULL, "
                    "created_at REAL NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO feed (team_id, sender_id, content, created_at) "
                    "SELECT team_id, sender, content, created_at FROM messages"
                )
                conn.execute("DROP TABLE messages")
            elif "feed" not in tables:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS feed ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "team_id TEXT NOT NULL REFERENCES teams(id), "
                    "sender_id TEXT NOT NULL, "
                    "content TEXT NOT NULL, "
                    "created_at REAL NOT NULL)"
                )

        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- Teams --

    def create_team(self, team_id: str, task: str, config: dict | None = None) -> None:
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO teams (id, task, status, created_at, updated_at, config) "
                "VALUES (?, ?, 'running', ?, ?, ?)",
                (team_id, task, now, now, json.dumps(config) if config else None),
            )

    def get_team(self, team_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            return dict(row) if row else None

    def update_team_status(self, team_id: str, status: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE teams SET status = ?, updated_at = ? WHERE id = ?",
                (status, time.time(), team_id),
            )

    def list_teams(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM teams ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def get_dead_teams_before(self, cutoff: float) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM teams WHERE status IN ('dead', 'terminated') AND updated_at < ?",
                (cutoff,),
            ).fetchall()
            return [r["id"] for r in rows]

    def delete_team(self, team_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM events WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM feed WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM file_locks WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM agents WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    # -- Agents --

    def create_agent(
        self,
        agent_id: str,
        team_id: str,
        task: str,
        role: str = "worker",
        model: str | None = None,
        backend: str = "cursor",
        worktree: str | None = None,
    ) -> None:
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO agents "
                "(id, team_id, role, task, status, model, backend, worktree, "
                " created_at, updated_at, stall_seconds, max_runtime) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, 1800, 1800)",
                (agent_id, team_id, role, task, model, backend, worktree, now, now),
            )

    def get_agent(self, agent_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return dict(row) if row else None

    def update_agent(self, agent_id: str, **kwargs) -> None:
        kwargs["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [agent_id]
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE agents SET {set_clause} WHERE id = ?",
                values,
            )

    def list_agents(self, team_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if team_id:
                rows = conn.execute(
                    "SELECT * FROM agents WHERE team_id = ? ORDER BY created_at",
                    (team_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]

    def update_heartbeat(self, agent_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE agents SET last_heartbeat = ?, updated_at = ? WHERE id = ?",
                (time.time(), time.time(), agent_id),
            )

    # -- Feed (shared team chat) --

    def post_to_feed(self, team_id: str, sender_id: str, content: str) -> int:
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO feed (team_id, sender_id, content, created_at) VALUES (?, ?, ?, ?)",
                (team_id, sender_id, content, now),
            )
            return cursor.lastrowid

    def get_feed(self, team_id: str, limit: int = 50, since: float | None = None) -> list[dict]:
        with self._connect() as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM feed WHERE team_id = ? AND created_at > ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (team_id, since, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM feed WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
                    (team_id, limit),
                ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # -- Events --

    def log_event(
        self,
        team_id: str,
        event_type: str,
        agent_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO events (team_id, agent_id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    team_id,
                    agent_id,
                    event_type,
                    json.dumps(payload) if payload else None,
                    time.time(),
                ),
            )

    # -- File Locks --

    def acquire_lock(self, file_path: str, team_id: str, agent_id: str, pid: int) -> bool:
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO file_locks (file_path, team_id, agent_id, pid, locked_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (file_path, team_id, agent_id, pid, time.time()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def release_lock(self, file_path: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM file_locks WHERE file_path = ?", (file_path,))

    def release_agent_locks(self, agent_id: str) -> int:
        with self.transaction() as conn:
            cursor = conn.execute("DELETE FROM file_locks WHERE agent_id = ?", (agent_id,))
            return cursor.rowcount

    def list_locks(self, team_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if team_id:
                rows = conn.execute(
                    "SELECT * FROM file_locks WHERE team_id = ?", (team_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM file_locks").fetchall()
            return [dict(r) for r in rows]
