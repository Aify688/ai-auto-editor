"""SQLite persistence. Large files never go in the database: only paths relative to DATA_DIR."""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    doc TEXT NOT NULL,
    render TEXT,
    history TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    position INTEGER NOT NULL,
    duration REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    has_audio INTEGER,
    info TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT,
    error TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS media_project ON media(project_id, position);
CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project_id, created_at);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            config.ensure_dirs()
            _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _conn.executescript(SCHEMA)
            _migrate(_conn)
        return _conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that didn't exist in earlier versions of the schema (SQLite has no ALTER ... IF NOT EXISTS)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if "history" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN history TEXT")


def execute(sql: str, args: tuple = ()) -> int:
    with _lock:
        return connect().execute(sql, args).rowcount


def query(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    with _lock:
        return [dict(r) for r in connect().execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict[str, Any] | None:
    rows = query(sql, args)
    return rows[0] if rows else None


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
