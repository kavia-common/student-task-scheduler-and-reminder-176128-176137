import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

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
                    priority INTEGER DEFAULT 2, -- 3/2/1 high/med/low
                    estimated_minutes INTEGER DEFAULT 0,
                    due_datetime TEXT, -- ISO 8601 including time
                    status TEXT DEFAULT 'open', -- open, in_progress, done, canceled
                    recurrence TEXT DEFAULT 'none', -- none/daily/weekly/monthly
                    recurrence_end_date TEXT, -- ISO date
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

                CREATE INDEX IF NOT EXISTS idx_tasks_due_datetime ON tasks(due_datetime);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
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


def _upsert_initial_reminder(cur: sqlite3.Cursor, task_id: int, due_iso: Optional[str]) -> None:
    """
    Create or update a reminder aligned to the task's due datetime.
    If due_iso is None, do nothing.
    """
    if not due_iso:
        return
    # If a reminder exists for this task and is not sent, update its remind_at, else insert
    cur.execute("SELECT id, sent FROM reminders WHERE task_id = ? ORDER BY id ASC LIMIT 1", (task_id,))
    existing = cur.fetchone()
    if existing:
        cur.execute("UPDATE reminders SET remind_at = ?, sent = 0 WHERE id = ?", (due_iso, int(existing["id"])))
    else:
        cur.execute(
            "INSERT INTO reminders (task_id, remind_at, sent, created_at) VALUES (?, ?, 0, datetime('now'))",
            (task_id, due_iso),
        )


# PUBLIC_INTERFACE
def create_task(
    title: str,
    description: str = "",
    category_name: Optional[str] = None,
    priority: int = 2,
    estimated_minutes: int = 0,
    due_datetime: Optional[str] = None,  # ISO 8601 "YYYY-MM-DDTHH:MM"
    status: str = "open",
    recurrence: str = "none",  # none/daily/weekly/monthly
    recurrence_end_date: Optional[str] = None,  # ISO date "YYYY-MM-DD"
) -> int:
    """Create a task with full attributes and create initial reminder for due_datetime."""
    if not title or not title.strip():
        raise ValueError("Task title is required.")
    if estimated_minutes is not None and estimated_minutes < 0:
        raise ValueError("Estimated minutes must be >= 0.")
    if priority not in (1, 2, 3, 4, 5) and priority not in (1, 2, 3):
        # Normalize priority to 1..3 scale if 5-point given
        if isinstance(priority, int) and 1 <= priority <= 5:
            priority = 3 if priority >= 4 else 2 if priority >= 2 else 1
        else:
            raise ValueError("Priority must be in {1,2,3} or 1..5 scale.")
    # validate due_datetime if present
    if due_datetime:
        try:
            datetime.fromisoformat(due_datetime)
        except Exception:
            raise ValueError("Invalid due date/time format. Use ISO 8601 e.g., 2025-01-31T14:30")
    # validate recurrence_end_date
    if recurrence_end_date:
        try:
            datetime.fromisoformat(recurrence_end_date)
        except Exception:
            raise ValueError("Invalid recurrence end date format. Use YYYY-MM-DD")
    if recurrence not in ("none", "daily", "weekly", "monthly"):
        raise ValueError("Invalid recurrence value.")
    if status not in ("open", "in_progress", "done", "canceled"):
        raise ValueError("Invalid status value.")

    with get_cursor() as cur:
        cat_id = _get_or_create_category(cur, category_name)
        cur.execute(
            """
            INSERT INTO tasks (title, description, category_id, priority, estimated_minutes, due_datetime,
                               status, recurrence, recurrence_end_date, completed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? IN ('done') THEN 1 ELSE 0 END, datetime('now'), datetime('now'))
            """,
            (
                title.strip(),
                (description or "").strip(),
                cat_id,
                int(priority),
                int(estimated_minutes or 0),
                due_datetime,
                status,
                recurrence,
                recurrence_end_date,
                status,
            ),
        )
        task_id = int(cur.lastrowid)
        _upsert_initial_reminder(cur, task_id, due_datetime)
        return task_id


# PUBLIC_INTERFACE
def update_task(
    task_id: int,
    title: str,
    description: str,
    category_name: Optional[str],
    priority: int,
    estimated_minutes: int,
    due_datetime: Optional[str],
    status: str,
    recurrence: str,
    recurrence_end_date: Optional[str],
) -> None:
    """Update a task and its initial reminder aligned to due_datetime."""
    if not title or not title.strip():
        raise ValueError("Task title is required.")
    if estimated_minutes is not None and estimated_minutes < 0:
        raise ValueError("Estimated minutes must be >= 0.")
    if due_datetime:
        try:
            datetime.fromisoformat(due_datetime)
        except Exception:
            raise ValueError("Invalid due date/time format.")
    if recurrence_end_date:
        try:
            datetime.fromisoformat(recurrence_end_date)
        except Exception:
            raise ValueError("Invalid recurrence end date format.")
    if recurrence not in ("none", "daily", "weekly", "monthly"):
        raise ValueError("Invalid recurrence value.")
    if status not in ("open", "in_progress", "done", "canceled"):
        raise ValueError("Invalid status value.")

    with get_cursor() as cur:
        cat_id = _get_or_create_category(cur, category_name)
        cur.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, category_id = ?, priority = ?, estimated_minutes = ?,
                due_datetime = ?, status = ?, recurrence = ?, recurrence_end_date = ?, 
                completed = CASE WHEN ? IN ('done') THEN 1 ELSE 0 END,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                title.strip(),
                (description or "").strip(),
                cat_id,
                int(priority),
                int(estimated_minutes or 0),
                due_datetime,
                status,
                recurrence,
                recurrence_end_date,
                status,
                int(task_id),
            ),
        )
        _upsert_initial_reminder(cur, int(task_id), due_datetime)


# PUBLIC_INTERFACE
# PUBLIC_INTERFACE
def delete_task(task_id: int) -> None:
    """Delete a task (cascades to reminders)."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))


# PUBLIC_INTERFACE
# PUBLIC_INTERFACE
def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    """Return a single task with its category name."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.*, COALESCE(c.name,'') as category
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.id = ?
            """,
            (int(task_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# PUBLIC_INTERFACE
def list_tasks(
    limit: int = 200,
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority_min: Optional[int] = None,
    priority_max: Optional[int] = None,
    date_range: Optional[Tuple[str, str]] = None,  # ("YYYY-MM-DD","YYYY-MM-DD")
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return a list of tasks with filters and search."""
    where = []
    params: List[Any] = []
    if status and status != "any":
        where.append("t.status = ?")
        params.append(status)
    if category and category != "any":
        where.append("c.name = ?")
        params.append(category)
    if priority_min is not None:
        where.append("t.priority >= ?")
        params.append(int(priority_min))
    if priority_max is not None:
        where.append("t.priority <= ?")
        params.append(int(priority_max))
    if date_range and date_range[0]:
        where.append("date(t.due_datetime) >= date(?)")
        params.append(date_range[0])
    if date_range and len(date_range) > 1 and date_range[1]:
        where.append("date(t.due_datetime) <= date(?)")
        params.append(date_range[1])
    if search and search.strip():
        where.append("(t.title LIKE ? OR t.description LIKE ?)")
        like = f"%{search.strip()}%"
        params.extend([like, like])

    sql = """
        SELECT t.id, t.title, t.description, t.priority, t.estimated_minutes,
               t.due_datetime, t.status, t.recurrence, t.recurrence_end_date,
               t.completed, COALESCE(c.name,'') as category
        FROM tasks t
        LEFT JOIN categories c ON t.category_id = c.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(t.due_datetime, '9999-12-31T23:59') ASC, t.created_at DESC LIMIT ?"
    params.append(int(limit))
    with get_cursor() as cur:
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]


# PUBLIC_INTERFACE
# PUBLIC_INTERFACE
def list_categories() -> List[str]:
    """Return distinct category names."""
    with get_cursor() as cur:
        cur.execute("SELECT name FROM categories ORDER BY name ASC")
        return [r["name"] for r in cur.fetchall()]


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
              AND due_datetime IS NOT NULL
              AND date(due_datetime) = date('now', 'localtime')
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
