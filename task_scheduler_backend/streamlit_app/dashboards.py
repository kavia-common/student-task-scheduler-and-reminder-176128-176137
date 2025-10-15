from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from . import db


@dataclass
class DashboardFilters:
    """Filters for dashboard analytics computations."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    category: Optional[str] = None  # 'any' means no filter
    status: Optional[str] = None    # 'any' means no filter

    def as_date_strings(self) -> Tuple[Optional[str], Optional[str]]:
        """Return (start_iso, end_iso) date strings for SQL date() comparisons."""
        s = self.start_date.isoformat() if self.start_date else None
        e = self.end_date.isoformat() if self.end_date else None
        return s, e


def _where_clauses_for_filters(f: DashboardFilters) -> Tuple[str, List[Any]]:
    """Build SQL where clauses for tasks table according to filters."""
    clauses: List[str] = []
    params: List[Any] = []

    # Category
    if f.category and f.category != "any":
        clauses.append("COALESCE(c.name, '') = ?")
        params.append(f.category)

    # Status
    if f.status and f.status != "any":
        clauses.append("t.status = ?")
        params.append(f.status)

    # Date range applies to due_datetime if present
    s_iso, e_iso = f.as_date_strings()
    if s_iso:
        clauses.append("date(t.due_datetime) >= date(?)")
        params.append(s_iso)
    if e_iso:
        clauses.append("date(t.due_datetime) <= date(?)")
        params.append(e_iso)

    where_sql = ""
    if clauses:
        where_sql = " WHERE " + " AND ".join(clauses)
    return where_sql, params


# PUBLIC_INTERFACE
def get_kpis(filters: DashboardFilters) -> Dict[str, int]:
    """Return KPI counters respecting filters: total, pending, completed_today, completed_this_week, overdue."""
    where_sql, params = _where_clauses_for_filters(filters)

    with db.get_cursor() as cur:
        # Total tasks (respecting category/status/date filters)
        cur.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cur.fetchone() or {"cnt": 0})["cnt"])

        # Pending (completed = 0) with same filters plus completed=0
        cur.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql + (" AND " if where_sql else " WHERE ")} t.completed = 0
            """,
            tuple(params),
        )
        pending = int((cur.fetchone() or {"cnt": 0})["cnt"])

        # Completed today: completed=1 and updated_at today
        cur.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql + (" AND " if where_sql else " WHERE ")} t.completed = 1
              AND date(t.updated_at) = date('now','localtime')
            """,
            tuple(params),
        )
        completed_today = int((cur.fetchone() or {"cnt": 0})["cnt"])

        # Completed this week: Monday..Sunday of current local week
        # Calculate week start and end
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        cur.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql + (" AND " if where_sql else " WHERE ")} t.completed = 1
              AND date(t.updated_at) BETWEEN date(?) AND date(?)
            """,
            tuple(params + [week_start.isoformat(), week_end.isoformat()]),
        )
        completed_week = int((cur.fetchone() or {"cnt": 0})["cnt"])

        # Overdue: not completed and due date past today
        cur.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql + (" AND " if where_sql else " WHERE ")} t.completed = 0
              AND t.due_datetime IS NOT NULL
              AND date(t.due_datetime) < date('now','localtime')
            """,
            tuple(params),
        )
        overdue = int((cur.fetchone() or {"cnt": 0})["cnt"])

    return {
        "total": total,
        "pending": pending,
        "completed_today": completed_today,
        "completed_this_week": completed_week,
        "overdue": overdue,
    }


# PUBLIC_INTERFACE
def completion_trend_dataframe(filters: DashboardFilters) -> pd.DataFrame:
    """Dataframe with counts of tasks completed per day, respecting filters."""
    where_sql, params = _where_clauses_for_filters(filters)
    with db.get_cursor() as cur:
        cur.execute(
            f"""
            SELECT date(t.updated_at) as day, COUNT(*) as completed_count
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql + (" AND " if where_sql else " WHERE ")} t.completed = 1
            GROUP BY date(t.updated_at)
            ORDER BY date(t.updated_at) ASC
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["day", "completed_count"])
    df = pd.DataFrame([dict(r) for r in rows])
    # Ensure proper dtype
    df["day"] = pd.to_datetime(df["day"])
    df["completed_count"] = pd.to_numeric(df["completed_count"])
    return df


# PUBLIC_INTERFACE
def tasks_by_category_dataframe(filters: DashboardFilters) -> pd.DataFrame:
    """Dataframe with counts of tasks by category, respecting filters."""
    where_sql, params = _where_clauses_for_filters(filters)
    with db.get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COALESCE(c.name,'(uncategorized)') as category, COUNT(*) as cnt
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql}
            GROUP BY COALESCE(c.name,'(uncategorized)')
            ORDER BY cnt DESC
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["category", "cnt"])
    return pd.DataFrame([dict(r) for r in rows])


# PUBLIC_INTERFACE
def priority_distribution_dataframe(filters: DashboardFilters) -> pd.DataFrame:
    """Dataframe with counts of tasks grouped by priority, respecting filters."""
    where_sql, params = _where_clauses_for_filters(filters)
    with db.get_cursor() as cur:
        cur.execute(
            f"""
            SELECT t.priority as priority, COUNT(*) as cnt
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            {where_sql}
            GROUP BY t.priority
            ORDER BY t.priority DESC
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["priority", "cnt"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["priority"] = pd.to_numeric(df["priority"])
    df["cnt"] = pd.to_numeric(df["cnt"])
    return df
