"""SQLite state management for Phalanx — teams, agents, messages, events, locks."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

GLOBAL_DB_PATH = Path.home() / ".phalanx" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id          TEXT PRIMARY KEY,
    task        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',
    backend     TEXT NOT NULL,
    model       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    config      TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    team_id         TEXT REFERENCES teams(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'worker',
    task            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    pid             INTEGER,
    tmux_session    TEXT,
    chat_id         TEXT,
    worktree_path   TEXT,
    backend         TEXT NOT NULL,
    model           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    artifact_status TEXT,
    last_heartbeat  TEXT,
    attempts        INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    stall_seconds   INTEGER DEFAULT 180,
    max_runtime     INTEGER DEFAULT 3600
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    agent_id    TEXT REFERENCES agents(id),
    sender      TEXT NOT NULL,
    content     TEXT NOT NULL,
    delivered   INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS file_locks (
    file_path   TEXT PRIMARY KEY,
    team_id     TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    agent_id    TEXT NOT NULL REFERENCES agents(id),
    pid         INTEGER NOT NULL,
    locked_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     TEXT,
    agent_id    TEXT,
    event_type  TEXT NOT NULL,
    payload     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agents_team ON agents(team_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_messages_team ON messages(team_id);
CREATE INDEX IF NOT EXISTS idx_events_team ON events(team_id);
CREATE INDEX IF NOT EXISTS idx_file_locks_team ON file_locks(team_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_TEAM_COLUMNS = frozenset({
    "id", "task", "status", "backend", "model", "created_at", "updated_at", "config",
})

_AGENT_COLUMNS = frozenset({
    "id", "team_id", "role", "task", "status", "pid", "tmux_session", "chat_id",
    "worktree_path", "backend", "model", "created_at", "updated_at",
    "artifact_status", "last_heartbeat", "attempts", "max_retries",
    "stall_seconds", "max_runtime",
})


def _validate_columns(columns: set[str], allowed: frozenset[str], table: str) -> None:
    bad = columns - allowed
    if bad:
        raise ValueError(f"Invalid columns for {table}: {bad}")


class Database:
    """Thin wrapper around SQLite with WAL mode and foreign keys."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or GLOBAL_DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Teams ──────────────────────────────────────────────

    def create_team(self, team_id: str, task: str, backend: str,
                    model: str | None = None, config: dict | None = None) -> dict:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO teams (id, task, backend, model, config) VALUES (?, ?, ?, ?, ?)",
                (team_id, task, backend, model, json.dumps(config) if config else None),
            )
        return self.get_team(team_id)

    def get_team(self, team_id: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT * FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_teams(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self._get_conn().execute(
                "SELECT * FROM teams WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT * FROM teams ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_team(self, team_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now_iso()
        _validate_columns(set(fields.keys()), _TEAM_COLUMNS, "teams")
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [team_id]
        with self.transaction() as conn:
            conn.execute(f"UPDATE teams SET {sets} WHERE id = ?", vals)  # nosec B608

    def delete_team(self, team_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    # ── Agents ─────────────────────────────────────────────

    def create_agent(self, agent_id: str, team_id: str, role: str, task: str,
                     backend: str, model: str | None = None, **extra: Any) -> dict:
        cols = ["id", "team_id", "role", "task", "backend", "model"] + list(extra.keys())
        _validate_columns(set(cols), _AGENT_COLUMNS, "agents")
        placeholders = ", ".join(["?"] * len(cols))
        vals = [agent_id, team_id, role, task, backend, model] + list(extra.values())
        with self.transaction() as conn:
            conn.execute(
                f"INSERT INTO agents ({', '.join(cols)}) VALUES ({placeholders})", vals  # nosec B608
            )
        return self.get_agent(agent_id)

    def get_agent(self, agent_id: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_agents(self, team_id: str | None = None, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM agents WHERE 1=1"
        params: list[Any] = []
        if team_id:
            query += " AND team_id = ?"
            params.append(team_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at"
        return [dict(r) for r in self._get_conn().execute(query, params).fetchall()]

    def update_agent(self, agent_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now_iso()
        _validate_columns(set(fields.keys()), _AGENT_COLUMNS, "agents")
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [agent_id]
        with self.transaction() as conn:
            conn.execute(f"UPDATE agents SET {sets} WHERE id = ?", vals)  # nosec B608

    def delete_agent(self, agent_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))

    # ── Messages ───────────────────────────────────────────

    def insert_message(self, team_id: str, sender: str, content: str,
                       agent_id: str | None = None, delivered: bool = False) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO messages (team_id, agent_id, sender, content, delivered) "
                "VALUES (?, ?, ?, ?, ?)",
                (team_id, agent_id, sender, content, int(delivered)),
            )
            return cur.lastrowid

    def get_messages(self, team_id: str, agent_id: str | None = None) -> list[dict]:
        if agent_id:
            rows = self._get_conn().execute(
                "SELECT * FROM messages WHERE team_id = ? AND agent_id = ? ORDER BY created_at",
                (team_id, agent_id),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT * FROM messages WHERE team_id = ? ORDER BY created_at", (team_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── File Locks ─────────────────────────────────────────

    def acquire_lock(self, file_path: str, team_id: str, agent_id: str, pid: int) -> bool:
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO file_locks (file_path, team_id, agent_id, pid) "
                    "VALUES (?, ?, ?, ?)",
                    (file_path, team_id, agent_id, pid),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def release_lock(self, file_path: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM file_locks WHERE file_path = ?", (file_path,))

    def release_agent_locks(self, agent_id: str) -> int:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM file_locks WHERE agent_id = ?", (agent_id,))
            return cur.rowcount

    def get_lock(self, file_path: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT * FROM file_locks WHERE file_path = ?", (file_path,)
        ).fetchone()
        return dict(row) if row else None

    def list_locks(self, team_id: str) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT * FROM file_locks WHERE team_id = ? ORDER BY locked_at", (team_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Events ─────────────────────────────────────────────

    def insert_event(self, event_type: str, team_id: str | None = None,
                     agent_id: str | None = None, payload: dict | None = None) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO events (team_id, agent_id, event_type, payload) "
                "VALUES (?, ?, ?, ?)",
                (team_id, agent_id, event_type, json.dumps(payload) if payload else None),
            )
            return cur.lastrowid

    def get_events(self, team_id: str | None = None, event_type: str | None = None,
                   limit: int = 100) -> list[dict]:
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if team_id:
            query += " AND team_id = ?"
            params.append(team_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._get_conn().execute(query, params).fetchall()]

    # ── GC Queries ─────────────────────────────────────────

    def get_stale_teams(self, gc_hours: int = 24) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT * FROM teams WHERE status IN ('dead', 'failed') "
            "AND updated_at < datetime('now', ? || ' hours')",
            (f"-{gc_hours}",),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stale_locks(self) -> list[dict]:
        """Return all locks — caller checks if PID is alive."""
        rows = self._get_conn().execute("SELECT * FROM file_locks").fetchall()
        return [dict(r) for r in rows]
