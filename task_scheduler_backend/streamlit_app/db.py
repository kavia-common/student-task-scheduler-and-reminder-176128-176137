import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Generator, List, Optional

from .settings import get_settings

# A global process-wide lock to serialize initialization
_init_lock = threading.Lock()
_db_initialized = False

# Create a thread-local storage for connections
_thread_local = threading.local()


def get_db_path() -> str:
    """Return the database file path, defaults to ./data/app.db within container."""
    settings = get_settings()
    base_dir = settings.DATA_DIR
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "app.db")


def _get_connection() -> sqlite3.Connection:
    """
    Get or create a SQLite connection bound to the current thread.
    Uses check_same_thread=False but we still prefer per-thread connections.
    """
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = sqlite3.connect(get_db_path(), check_same_thread=False, isolation_level=None)
        _thread_local.conn.row_factory = sqlite3.Row
        # Enforce foreign keys
        _thread_local.conn.execute("PRAGMA foreign_keys = ON;")
    return _thread_local.conn


@contextmanager
def get_cursor() -> Generator[sqlite3.Cursor, None, None]:
    """Context manager that yields a cursor from the per-thread connection."""
    conn = _get_connection()
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


def init_db() -> None:
    """
    Initialize the SQLite database schema once per process.
    Safe to call multiple times.
    """
    global _db_initialized
    if _db_initialized:
        return

    with _init_lock:
        if _db_initialized:
            return

        with get_cursor() as cur:
            # Create tables
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    category_id INTEGER,
                    due_date TEXT,
                    completed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    remind_at TEXT NOT NULL,
                    sent INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_minutes INTEGER,
                    notes TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
                CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at);
                CREATE INDEX IF NOT EXISTS idx_reminders_sent ON reminders(sent);
                """
            )

        _db_initialized = True


def _get_or_create_category(cur: sqlite3.Cursor, name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    cur.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (name.strip(),))
    cur.execute("SELECT id FROM categories WHERE name = ?", (name.strip(),))
    row = cur.fetchone()
    return int(row["id"]) if row else None


def add_task(title: str, description: str = "", category_name: Optional[str] = None, due_date: Optional[date] = None) -> int:
    """Insert a task and optional category."""
    if not title or not title.strip():
        raise ValueError("Task title is required.")
    with get_cursor() as cur:
        cat_id = _get_or_create_category(cur, category_name)
        due_text = due_date.isoformat() if isinstance(due_date, date) else None
        cur.execute(
            """
            INSERT INTO tasks (title, description, category_id, due_date, completed, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, datetime('now'), datetime('now'))
            """,
            (title.strip(), description.strip() if description else "", cat_id, due_text),
        )
        return int(cur.lastrowid)


def list_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    """Return a list of tasks joined with category names."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.title, t.description, t.due_date, t.completed,
                   COALESCE(c.name, '') as category
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            ORDER BY COALESCE(t.due_date, '9999-12-31') ASC, t.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def count_open_tasks() -> int:
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE completed = 0")
        row = cur.fetchone()
        return int(row["cnt"] if row else 0)


def count_due_today() -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) as cnt
            FROM tasks
            WHERE completed = 0
              AND due_date IS NOT NULL
              AND date(due_date) = date('now', 'localtime')
            """
        )
        row = cur.fetchone()
        return int(row["cnt"] if row else 0)


def count_pomodoro_today() -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) as cnt
            FROM pomodoro_sessions
            WHERE date(started_at) = date('now', 'localtime')
            """
        )
        row = cur.fetchone()
        return int(row["cnt"] if row else 0)


def get_due_unsent_reminders(now_iso: str) -> List[Dict[str, Any]]:
    """Return reminders due at or before now that have not been sent."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.task_id, r.remind_at, r.sent, t.title
            FROM reminders r
            LEFT JOIN tasks t ON r.task_id = t.id
            WHERE r.sent = 0
              AND datetime(r.remind_at) <= datetime(?, 'localtime')
            ORDER BY r.remind_at ASC
            """,
            (now_iso,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int) -> None:
    with get_cursor() as cur:
        cur.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
