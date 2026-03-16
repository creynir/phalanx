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

SCHEMA_VERSION = 7

_VALID_AGENT_ROLES = frozenset({"lead", "agent"})

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
    role            TEXT NOT NULL DEFAULT 'agent' CHECK(role IN ('lead', 'agent')),
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
    prompt_state    TEXT,
    prompt_screen   TEXT,
    ghost_restart_count INTEGER DEFAULT 0,
    max_ghost_restarts  INTEGER DEFAULT 5,
    soul_path       TEXT
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

CREATE TABLE IF NOT EXISTS token_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL,
    backend         TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    recorded_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS team_context (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         TEXT NOT NULL,
    skill_run_id    TEXT,
    step_name       TEXT,
    context_type    TEXT NOT NULL CHECK(context_type IN ('convention','pattern','constraint','discovery')),
    content         TEXT NOT NULL,
    content_hash    TEXT,
    source_agent_id TEXT,
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_runs (
    id              TEXT PRIMARY KEY,
    team_id         TEXT NOT NULL,
    skill_name      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    dag_json        TEXT,
    completed_steps TEXT DEFAULT '[]',
    current_step    TEXT,
    step_artifacts  TEXT DEFAULT '{}',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS engineering_manager_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         TEXT NOT NULL,
    skill_run_id    TEXT,
    trigger_source  TEXT NOT NULL CHECK(trigger_source IN ('team_lead_escalation','ghost_loop','rate_limit_storm','human')),
    decision_json   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','applied','rejected','failed')),
    created_at      REAL NOT NULL,
    applied_at      REAL
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

        if from_version < 4:
            try:
                conn.execute("ALTER TABLE agents DROP COLUMN stall_seconds")
                conn.execute("ALTER TABLE agents DROP COLUMN max_runtime")
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("Migration v4 column drop failed: %s", e)

        if from_version < 5:
            self._migrate_to_v5(conn)

        if from_version < 6:
            self._migrate_to_v6(conn)

        if from_version < 7:
            self._migrate_to_v7(conn)

        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    def _migrate_to_v5(self, conn: sqlite3.Connection) -> None:
        """v5: Add token_usage, team_context, skill_runs tables."""
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

        if "token_usage" not in tables:
            conn.execute(
                "CREATE TABLE token_usage ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "team_id TEXT NOT NULL, "
                "agent_id TEXT NOT NULL, "
                "role TEXT NOT NULL, "
                "backend TEXT NOT NULL, "
                "model TEXT, "
                "input_tokens INTEGER NOT NULL DEFAULT 0, "
                "output_tokens INTEGER NOT NULL DEFAULT 0, "
                "total_tokens INTEGER NOT NULL DEFAULT 0, "
                "recorded_at REAL NOT NULL)"
            )

        if "team_context" not in tables:
            conn.execute(
                "CREATE TABLE team_context ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "team_id TEXT NOT NULL, "
                "skill_run_id TEXT, "
                "step_name TEXT, "
                "context_type TEXT NOT NULL CHECK(context_type IN ('convention','pattern','constraint','discovery')), "
                "content TEXT NOT NULL, "
                "content_hash TEXT, "
                "source_agent_id TEXT, "
                "created_at REAL NOT NULL)"
            )

        if "skill_runs" not in tables:
            conn.execute(
                "CREATE TABLE skill_runs ("
                "id TEXT PRIMARY KEY, "
                "team_id TEXT NOT NULL, "
                "skill_name TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'running', "
                "dag_json TEXT, "
                "completed_steps TEXT DEFAULT '[]', "
                "current_step TEXT, "
                "step_artifacts TEXT DEFAULT '{}', "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL)"
            )

    def _migrate_to_v6(self, conn: sqlite3.Connection) -> None:
        """v6: Add ghost_restart_count to agents, engineering manager state table."""
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
        if "ghost_restart_count" not in cols:
            conn.execute("ALTER TABLE agents ADD COLUMN ghost_restart_count INTEGER DEFAULT 0")
        if "max_ghost_restarts" not in cols:
            conn.execute("ALTER TABLE agents ADD COLUMN max_ghost_restarts INTEGER DEFAULT 5")

        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "engineering_manager_state" not in tables:
            conn.execute(
                "CREATE TABLE engineering_manager_state ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "team_id TEXT NOT NULL, "
                "skill_run_id TEXT, "
                "trigger_source TEXT NOT NULL CHECK(trigger_source IN "
                "('team_lead_escalation','ghost_loop','rate_limit_storm','human')), "
                "decision_json TEXT, "
                "status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN "
                "('pending','applied','rejected','failed')), "
                "created_at REAL NOT NULL, "
                "applied_at REAL)"
            )

    def _migrate_to_v7(self, conn: sqlite3.Connection) -> None:
        """v7: Add soul_path column to agents table."""
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
        if "soul_path" not in cols:
            conn.execute("ALTER TABLE agents ADD COLUMN soul_path TEXT")

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
            conn.execute("DELETE FROM token_usage WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM team_context WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM skill_runs WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM events WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM feed WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM file_locks WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM engineering_manager_state WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM agents WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    # -- Agents --

    def create_agent(
        self,
        agent_id: str,
        team_id: str,
        task: str,
        role: str = "agent",
        model: str | None = None,
        backend: str = "cursor",
        worktree: str | None = None,
        soul_path: str | None = None,
    ) -> None:
        if role not in _VALID_AGENT_ROLES:
            raise ValueError(
                f"Invalid agent role {role!r}. Must be one of: {sorted(_VALID_AGENT_ROLES)}"
            )
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO agents "
                "(id, team_id, role, task, status, model, backend, worktree, "
                " created_at, updated_at, soul_path) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
                (agent_id, team_id, role, task, model, backend, worktree, now, now, soul_path),
            )

    def get_agent(self, agent_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return dict(row) if row else None

    def find_team_for_agent(self, agent_id: str) -> str | None:
        """Return the team_id for the given agent_id, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT team_id FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
            return row["team_id"] if row else None

    def update_agent(self, agent_id: str, **kwargs) -> None:
        if "role" in kwargs and kwargs["role"] not in _VALID_AGENT_ROLES:
            raise ValueError(
                f"Invalid agent role {kwargs['role']!r}. Must be one of: {sorted(_VALID_AGENT_ROLES)}"
            )
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
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE agents SET last_heartbeat = ?, updated_at = ? WHERE id = ?",
                (now, now, agent_id),
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
            if since is not None:
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

    # -- Token Usage (v1.0.0) --

    def record_token_usage(
        self,
        team_id: str,
        agent_id: str,
        role: str,
        backend: str,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        total = input_tokens + output_tokens
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO token_usage "
                "(team_id, agent_id, role, backend, model, input_tokens, "
                " output_tokens, total_tokens, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    team_id,
                    agent_id,
                    role,
                    backend,
                    model,
                    input_tokens,
                    output_tokens,
                    total,
                    time.time(),
                ),
            )

    def get_team_token_usage(self, team_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM token_usage WHERE team_id = ? ORDER BY recorded_at",
                (team_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_agent_token_usage(self, agent_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM token_usage WHERE agent_id = ? ORDER BY recorded_at",
                (agent_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Team Context / Continual Learning (v1.0.0) --

    def add_team_context(
        self,
        team_id: str,
        context_type: str,
        content: str,
        content_hash: str | None = None,
        skill_run_id: str | None = None,
        step_name: str | None = None,
        source_agent_id: str | None = None,
    ) -> int | None:
        with self.transaction() as conn:
            if content_hash:
                existing = conn.execute(
                    "SELECT id FROM team_context WHERE team_id = ? AND content_hash = ?",
                    (team_id, content_hash),
                ).fetchone()
                if existing:
                    return None  # deduplicate

            cursor = conn.execute(
                "INSERT INTO team_context "
                "(team_id, skill_run_id, step_name, context_type, content, "
                " content_hash, source_agent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    team_id,
                    skill_run_id,
                    step_name,
                    context_type,
                    content,
                    content_hash,
                    source_agent_id,
                    time.time(),
                ),
            )
            return cursor.lastrowid

    def get_team_context(self, team_id: str, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM team_context WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
                (team_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_team_context(self, team_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM team_context WHERE team_id = ?", (team_id,))

    # -- Skill Runs / Checkpoints (v1.0.0) --

    def create_skill_run(
        self,
        run_id: str,
        team_id: str,
        skill_name: str,
        dag_json: str | None = None,
    ) -> None:
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO skill_runs "
                "(id, team_id, skill_name, status, dag_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 'running', ?, ?, ?)",
                (run_id, team_id, skill_name, dag_json, now, now),
            )

    def get_skill_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skill_runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def update_skill_run(self, run_id: str, **kwargs) -> None:
        kwargs["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [run_id]
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE skill_runs SET {set_clause} WHERE id = ?",
                values,
            )

    def save_checkpoint(
        self,
        run_id: str,
        step_name: str,
        step_result: str | None = None,
    ) -> None:
        """Mark a step as completed in a skill run and optionally save its artifact."""
        run = self.get_skill_run(run_id)
        if run is None:
            return

        completed = json.loads(run.get("completed_steps") or "[]")
        if step_name not in completed:
            completed.append(step_name)

        artifacts = json.loads(run.get("step_artifacts") or "{}")
        if step_result is not None:
            artifacts[step_name] = step_result

        self.update_skill_run(
            run_id,
            completed_steps=json.dumps(completed),
            step_artifacts=json.dumps(artifacts),
            current_step=None,
        )

    def load_checkpoint(self, run_id: str) -> dict | None:
        """Load checkpoint state for a skill run.

        Returns dict with completed_steps list and step_artifacts map,
        or None if the run doesn't exist.
        """
        run = self.get_skill_run(run_id)
        if run is None:
            return None
        return {
            "run_id": run_id,
            "status": run["status"],
            "completed_steps": json.loads(run.get("completed_steps") or "[]"),
            "current_step": run.get("current_step"),
            "step_artifacts": json.loads(run.get("step_artifacts") or "{}"),
        }

    def get_active_skill_run(self, team_id: str) -> dict | None:
        """Return the most recent 'running' skill run for a team, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_runs WHERE team_id = ? AND status = 'running' "
                "ORDER BY created_at DESC LIMIT 1",
                (team_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_skill_runs(self, team_id: str, limit: int = 5) -> list[dict]:
        """Return the most recent skill runs for a team, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_runs WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
                (team_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_events(self, team_id: str, limit: int = 30) -> list[dict]:
        """Return the most recent events for a team, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_type, agent_id, payload, created_at FROM events "
                "WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
                (team_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Ghost Restart Tracking (v1.0.0) --

    def increment_ghost_restart(self, agent_id: str) -> int:
        """Increment ghost_restart_count and return the new value.

        Used by the team monitor to track ghost session restart loops.
        When the count exceeds max_ghost_restarts, the agent is escalated
        to the Outer Loop instead of being restarted again.
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            return 0
        new_count = (agent.get("ghost_restart_count") or 0) + 1
        self.update_agent(agent_id, ghost_restart_count=new_count)
        return new_count

    def reset_ghost_restart_count(self, agent_id: str) -> None:
        """Reset ghost restart counter after successful recovery."""
        self.update_agent(agent_id, ghost_restart_count=0)

    def get_ghost_restart_limit(self, agent_id: str) -> int:
        """Return the max ghost restarts before Outer Loop escalation."""
        agent = self.get_agent(agent_id)
        if agent is None:
            return 5
        return agent.get("max_ghost_restarts") or 5

    # -- Engineering Manager State (v1.0.0) --

    def create_engineering_manager_entry(
        self,
        team_id: str,
        trigger_source: str,
        decision_json: str | None = None,
        skill_run_id: str | None = None,
    ) -> int:
        """Record an engineering manager activation. Returns the entry id."""
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO engineering_manager_state "
                "(team_id, skill_run_id, trigger_source, decision_json, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (team_id, skill_run_id, trigger_source, decision_json, now),
            )
            return cursor.lastrowid

    def update_engineering_manager_entry(self, entry_id: int, **kwargs) -> None:
        """Update an engineering manager state entry (e.g., mark applied/rejected)."""
        if "status" in kwargs and kwargs["status"] == "applied":
            kwargs["applied_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [entry_id]
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE engineering_manager_state SET {set_clause} WHERE id = ?",
                values,
            )

    def get_engineering_manager_history(self, team_id: str, limit: int = 20) -> list[dict]:
        """Get engineering manager activation history for a team."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM engineering_manager_state WHERE team_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (team_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
