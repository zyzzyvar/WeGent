from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    openid TEXT PRIMARY KEY,
                    nickname TEXT,
                    memory_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    openid TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(openid) REFERENCES users(openid) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    openid TEXT NOT NULL,
                    msg_id TEXT UNIQUE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ok',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(openid) REFERENCES users(openid) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    openid TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(openid) REFERENCES users(openid) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_memories_openid_created
                    ON memories(openid, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_openid_created
                    ON messages(openid, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_status_due
                    ON tasks(status, due_at);
                """
            )

    def ensure_user(self, openid: str) -> None:
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(openid, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(openid) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (openid, now, now),
            )

    def get_user(self, openid: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE openid = ?", (openid,)).fetchone()

    def set_memory_enabled(self, openid: str, enabled: bool) -> None:
        self.ensure_user(openid)
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET memory_enabled = ?, updated_at = ? WHERE openid = ?",
                (1 if enabled else 0, utc_now_iso(), openid),
            )

    def add_memory(self, openid: str, content: str) -> int:
        self.ensure_user(openid)
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memories(openid, content, created_at) VALUES (?, ?, ?)",
                (openid, content.strip(), utc_now_iso()),
            )
            return int(cursor.lastrowid)

    def list_memories(self, openid: str, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE openid = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (openid, limit),
                )
            )

    def clear_memories(self, openid: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE openid = ?", (openid,))
            return int(cursor.rowcount)

    def record_message(
        self,
        *,
        openid: str,
        role: str,
        content: str,
        msg_id: str | None = None,
        status: str = "ok",
    ) -> bool:
        self.ensure_user(openid)
        now = utc_now_iso()
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO messages(openid, msg_id, role, content, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (openid, msg_id, role, content, status, now, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def recent_messages(self, openid: str, limit: int = 8) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM messages
                WHERE openid = ? AND status = 'ok'
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (openid, limit),
            ).fetchall()
        return list(reversed(rows))

    def create_task(self, openid: str, title: str, prompt: str, due_at: str) -> int:
        self.ensure_user(openid)
        now = utc_now_iso()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks(openid, title, prompt, due_at, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (openid, title, prompt, due_at, now, now),
            )
            return int(cursor.lastrowid)

    def due_tasks(self, now_iso: str, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'pending' AND due_at <= ?
                    ORDER BY due_at ASC
                    LIMIT ?
                    """,
                    (now_iso, limit),
                )
            )

    def mark_task_running(self, task_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'running', updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (utc_now_iso(), task_id),
            )
            return cursor.rowcount == 1

    def complete_task(self, task_id: int, result: str, status: str = "done") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, result = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, result, utc_now_iso(), task_id),
            )

    def set_kv(self, key: str, value: Any, expires_at: int | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO kv(key, value, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at
                """,
                (key, payload, expires_at),
            )

    def get_kv(self, key: str) -> Any | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value, expires_at FROM kv WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            if row["expires_at"] is not None and int(row["expires_at"]) <= int(time.time()):
                conn.execute("DELETE FROM kv WHERE key = ?", (key,))
                return None
            return json.loads(row["value"])

