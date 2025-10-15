from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import db
from .settings import get_settings


@dataclass
class SuggestionWeights:
    """Weights for heuristic scoring."""
    WEIGHT_PRIORITY: float = 1.0
    WEIGHT_URGENCY: float = 1.0
    WEIGHT_OVERDUE_BOOST: float = 1.0
    WEIGHT_SHORT_TASK_BIAS: float = 0.5

    # Boundaries and defaults
    SHORT_TASK_THRESHOLD_MIN: int = 30  # minutes considered short
    URGENCY_WINDOW_HOURS: int = 72      # consider due within 72h strongly


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _priority_score(priority: Optional[int]) -> float:
    """
    Normalize priority into 0..1 where High(3)->1, Med(2)->0.6, Low(1)->0.3.
    If other scales appear, clamp into [0,1].
    """
    if priority is None:
        return 0.4
    try:
        p = int(priority)
    except Exception:
        return 0.4
    # Support 1..5 scale as well by mapping to 1..3
    if 1 <= p <= 5:
        if p > 3:
            p = 3
        elif p < 1:
            p = 1
    mapping = {3: 1.0, 2: 0.6, 1: 0.3}
    return float(mapping.get(p, max(0.0, min(1.0, p / 3.0))))


def _urgency_score(due_dt: Optional[datetime], window_hours: int) -> Tuple[float, bool]:
    """
    Return (urgency_score in 0..1, is_overdue).
    - If overdue: return 1.0 urgency and overdue flag.
    - If no due date: 0.2 baseline urgency.
    - If due within 'window_hours': scale linearly (closer -> higher).
    """
    if not due_dt:
        return 0.2, False
    now = datetime.now()
    if due_dt < now:
        return 1.0, True
    delta = due_dt - now
    total = timedelta(hours=max(1, int(window_hours)))
    # invert: 0 far, 1 close
    frac = 1.0 - min(1.0, max(0.0, delta / total))
    return float(frac), False


def _short_task_bonus(estimated_minutes: Optional[int], threshold_min: int) -> float:
    """
    Encourage quick wins: full bonus if <= threshold, taper to 0 by ~2x threshold.
    """
    if estimated_minutes is None:
        return 0.0
    est = max(0, int(estimated_minutes))
    if est <= threshold_min:
        return 1.0
    if est >= threshold_min * 2:
        return 0.0
    # linear falloff between threshold..2*threshold
    remaining = (threshold_min * 2) - est
    return max(0.0, remaining / float(threshold_min))


def _compute_score(row: Dict[str, Any], w: SuggestionWeights) -> Tuple[float, Dict[str, Any]]:
    """
    Compute total score and return with factors for explainability.
    """
    pri = _safe_int(row.get("priority"), 2)
    due = _parse_iso(row.get("due_datetime"))
    est = _safe_int(row.get("estimated_minutes"), 0)

    s_priority = _priority_score(pri)
    s_urgency, is_overdue = _urgency_score(due, w.URGENCY_WINDOW_HOURS)
    s_short = _short_task_bonus(est, w.SHORT_TASK_THRESHOLD_MIN)
    overdue_boost = 1.0 if is_overdue else 0.0

    total = (
        s_priority * w.WEIGHT_PRIORITY +
        s_urgency * w.WEIGHT_URGENCY +
        overdue_boost * w.WEIGHT_OVERDUE_BOOST +
        s_short * w.WEIGHT_SHORT_TASK_BIAS
    )

    factors = {
        "priority_norm": round(s_priority, 3),
        "urgency": round(s_urgency, 3),
        "overdue": is_overdue,
        "short_task_bonus": round(s_short, 3),
        "weights": {
            "priority": w.WEIGHT_PRIORITY,
            "urgency": w.WEIGHT_URGENCY,
            "overdue": w.WEIGHT_OVERDUE_BOOST,
            "short": w.WEIGHT_SHORT_TASK_BIAS,
        },
    }
    return float(round(total, 4)), factors


def _load_weights_from_settings() -> SuggestionWeights:
    """
    Read weights from Settings with safe fallbacks.
    """
    s = get_settings()
    try:
        return SuggestionWeights(
            WEIGHT_PRIORITY=float(getattr(s, "SUGGESTION_WEIGHT_PRIORITY", 1.0)),
            WEIGHT_URGENCY=float(getattr(s, "SUGGESTION_WEIGHT_URGENCY", 1.0)),
            WEIGHT_OVERDUE_BOOST=float(getattr(s, "SUGGESTION_WEIGHT_OVERDUE_BOOST", 1.0)),
            WEIGHT_SHORT_TASK_BIAS=float(getattr(s, "SUGGESTION_WEIGHT_SHORT_TASK_BIAS", 0.5)),
            SHORT_TASK_THRESHOLD_MIN=int(getattr(s, "SUGGESTION_SHORT_TASK_THRESHOLD_MIN", 30)),
            URGENCY_WINDOW_HOURS=int(getattr(s, "SUGGESTION_URGENCY_WINDOW_HOURS", 72)),
        )
    except Exception:
        # Absolute fallback to sane defaults
        return SuggestionWeights()


# PUBLIC_INTERFACE
def get_top_suggestions(limit: int = 3, for_minutes: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return top next-task suggestions based on heuristic scoring.

    - Considers only tasks that are not completed and not canceled.
    - If for_minutes is provided, prefer tasks with estimated_minutes <= for_minutes.
    - Scoring uses priority, urgency to due date, overdue boost, and short-task bias.
    - Returns a list of dicts with task fields plus 'score' and 'factors'.
    """
    w = _load_weights_from_settings()

    where = ["t.completed = 0", "t.status NOT IN ('canceled')"]
    params: List[Any] = []
    if for_minutes is not None:
        # Prefer shorter tasks by a soft filter: include all, but we'll add a small penalty for longer later
        pass

    sql = """
        SELECT t.id, t.title, t.description, t.priority, t.estimated_minutes,
               t.due_datetime, t.status, COALESCE(c.name,'') as category
        FROM tasks t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE {where}
        ORDER BY COALESCE(t.due_datetime, '9999-12-31T23:59') ASC
        LIMIT 500
    """.format(where=" AND ".join(where))

    rows: List[Dict[str, Any]] = []
    with db.get_cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return []

    # Compute scores
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in rows:
        score, factors = _compute_score(r, w)
        # Add soft penalty if for_minutes set and task longer than slot
        if for_minutes is not None:
            est = _safe_int(r.get("estimated_minutes"), 0)
            if est > 0 and est > int(for_minutes):
                # penalize by how much it exceeds the slot, capped
                over = min(120, est - int(for_minutes))  # cap excess at 2h
                penalty = min(0.5, over / 240.0)  # up to -0.5
                score = max(0.0, score - penalty)
                factors["slot_penalty"] = round(penalty, 3)
        r_with = dict(r)
        r_with["score"] = float(round(score, 4))
        r_with["factors"] = factors
        scored.append((score, r_with))

    # Sort and take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [item for _, item in scored[: max(1, int(limit))]]
    return top
