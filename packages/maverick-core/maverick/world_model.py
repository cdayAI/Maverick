"""Persistent world model. SQLite with FTS5 for cheap recall.

This is the consumer wedge: not chat history, but a typed model of the user
and their ongoing work that survives restarts.

v0.1.1: added schema_version table + migrations dispatch. When SCHEMA is
changed in a future version, append the upgrade SQL to MIGRATIONS keyed by
the new version number; existing user DBs will apply it on next open.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_DB = Path.home() / ".maverick" / "world.db"

# Bump when adding a migration to MIGRATIONS. New DBs are created at this
# version; existing DBs are upgraded by applying every migration with
# version > current_version.
SCHEMA_VERSION = 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES goals(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | active | blocked | done | abandoned
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    deadline REAL,
    result TEXT
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    started_at REAL NOT NULL,
    ended_at REAL,
    summary TEXT,
    outcome TEXT  -- success | failure | interrupted
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source_episode_id INTEGER REFERENCES episodes(id),
    updated_at REAL NOT NULL,
    UNIQUE(key)
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    question TEXT NOT NULL,
    asked_at REAL NOT NULL,
    answer TEXT,
    answered_at REAL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content='messages', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


# Future migrations: MIGRATIONS[N] is the list of SQL statements to bring a
# DB from version N-1 to N. Example:
#
# MIGRATIONS = {
#     2: [
#         "ALTER TABLE goals ADD COLUMN priority INTEGER DEFAULT 0",
#         "CREATE INDEX idx_goals_priority ON goals(priority)",
#     ],
# }
MIGRATIONS: dict[int, list[str]] = {}


@dataclass
class Goal:
    id: int
    parent_id: Optional[int]
    title: str
    description: Optional[str]
    status: str
    created_at: float
    updated_at: float
    deadline: Optional[float]
    result: Optional[str]


@dataclass
class Question:
    id: int
    goal_id: Optional[int]
    question: str
    asked_at: float
    answer: Optional[str]
    answered_at: Optional[float]


class WorldModel:
    def __init__(self, path: Path = DEFAULT_DB):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._init_schema_version()
        self._apply_migrations()
        self.conn.commit()

    def _init_schema_version(self) -> None:
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,)
            )

    def _apply_migrations(self) -> None:
        """Run any migrations whose version > current schema_version."""
        current = self.conn.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()[0]
        target = SCHEMA_VERSION
        while current < target:
            next_version = current + 1
            migration = MIGRATIONS.get(next_version)
            if migration is None:
                # No migration defined yet; just bump the recorded version
                # so the gap closes (assumes idempotent CREATE TABLE IF NOT EXISTS
                # in SCHEMA covers new objects).
                break
            for stmt in migration:
                self.conn.execute(stmt)
            self.conn.execute("UPDATE schema_version SET version = ?", (next_version,))
            current = next_version

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        return row[0] if row else 0

    # ----- goals -----
    def create_goal(self, title: str, description: str = "", parent_id: Optional[int] = None) -> int:
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO goals(parent_id, title, description, status, created_at, updated_at) "
            "VALUES(?, ?, ?, 'pending', ?, ?)",
            (parent_id, title, description, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_goal_status(self, goal_id: int, status: str, result: Optional[str] = None) -> None:
        self.conn.execute(
            "UPDATE goals SET status = ?, updated_at = ?, result = COALESCE(?, result) WHERE id = ?",
            (status, time.time(), result, goal_id),
        )
        self.conn.commit()

    def get_goal(self, goal_id: int) -> Optional[Goal]:
        row = self.conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return Goal(**dict(row)) if row else None

    def list_goals(self, status: Optional[str] = None) -> list[Goal]:
        if status:
            rows = self.conn.execute("SELECT * FROM goals WHERE status = ? ORDER BY id", (status,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM goals ORDER BY id").fetchall()
        return [Goal(**dict(r)) for r in rows]

    def active_goal(self) -> Optional[Goal]:
        row = self.conn.execute(
            "SELECT * FROM goals WHERE status IN ('active', 'blocked') ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return Goal(**dict(row)) if row else None

    # ----- episodes -----
    def start_episode(self, goal_id: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO episodes(goal_id, started_at) VALUES(?, ?)", (goal_id, time.time())
        )
        self.conn.commit()
        return cur.lastrowid

    def end_episode(self, episode_id: int, summary: str, outcome: str) -> None:
        self.conn.execute(
            "UPDATE episodes SET ended_at = ?, summary = ?, outcome = ? WHERE id = ?",
            (time.time(), summary, outcome, episode_id),
        )
        self.conn.commit()

    # ----- facts -----
    def upsert_fact(self, key: str, value: str, episode_id: Optional[int] = None) -> None:
        self.conn.execute(
            "INSERT INTO facts(key, value, source_episode_id, updated_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, episode_id, time.time()),
        )
        self.conn.commit()

    def get_facts(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM facts ORDER BY updated_at DESC").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ----- questions -----
    def ask(self, question: str, goal_id: Optional[int] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO questions(goal_id, question, asked_at) VALUES(?, ?, ?)",
            (goal_id, question, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def answer(self, question_id: int, answer: str) -> None:
        self.conn.execute(
            "UPDATE questions SET answer = ?, answered_at = ? WHERE id = ?",
            (answer, time.time(), question_id),
        )
        self.conn.commit()

    def open_questions(self, goal_id: Optional[int] = None) -> list[Question]:
        if goal_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM questions WHERE answer IS NULL AND goal_id = ? ORDER BY id", (goal_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM questions WHERE answer IS NULL ORDER BY id"
            ).fetchall()
        return [Question(**dict(r)) for r in rows]

    def all_questions(self, goal_id: int) -> list[Question]:
        rows = self.conn.execute(
            "SELECT * FROM questions WHERE goal_id = ? ORDER BY id", (goal_id,)
        ).fetchall()
        return [Question(**dict(r)) for r in rows]

    # ----- messages -----
    def append_message(self, goal_id: int, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages(goal_id, role, content, ts) VALUES(?, ?, ?, ?)",
            (goal_id, role, content, time.time()),
        )
        self.conn.commit()

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT m.* FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
            "WHERE messages_fts MATCH ? ORDER BY m.ts DESC LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
