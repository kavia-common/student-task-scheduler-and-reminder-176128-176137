from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import streamlit as st

from . import db
from .utils import toast_info, toast_success, toast_warning, notify_placeholder


@dataclass
class PomodoroConfig:
    """Configuration for Pomodoro sessions."""
    focus_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    long_break_interval: int = 4  # after N focus sessions, take a long break


@dataclass
class PomodoroState:
    """Runtime state of the Pomodoro timer."""
    mode: str = "focus"  # focus | short_break | long_break
    time_left_sec: int = 25 * 60
    cycle_count: int = 0  # completed focus sessions within current set
    total_focus_completed: int = 0
    is_running: bool = False
    bound_task_id: Optional[int] = None
    current_session_start: Optional[datetime] = None
    # Guard to prevent duplicate ticker creation per session
    ticker_id: Optional[str] = None


# Process-wide ticker control to avoid duplicate ticking across reruns
_ticker_lock = threading.Lock()
_ticker_thread: Optional[threading.Thread] = None
_ticker_stop = threading.Event()


def _now() -> datetime:
    return datetime.now()


def _ensure_session_state(config: Optional[PomodoroConfig] = None) -> Tuple[PomodoroConfig, PomodoroState]:
    """Create default config/state in st.session_state if absent."""
    if "pomodoro_config" not in st.session_state:
        st.session_state["pomodoro_config"] = PomodoroConfig()
    if "pomodoro_state" not in st.session_state:
        cfg: PomodoroConfig = st.session_state["pomodoro_config"]
        st.session_state["pomodoro_state"] = PomodoroState(
            time_left_sec=cfg.focus_minutes * 60,
            mode="focus",
            is_running=False,
        )
    if config is not None:
        st.session_state["pomodoro_config"] = config
    return st.session_state["pomodoro_config"], st.session_state["pomodoro_state"]


def _persist_session(task_id: Optional[int], started_at: datetime, ended_at: datetime, duration_minutes: int, notes: str = "") -> None:
    """Insert a row into pomodoro_sessions."""
    try:
        with db.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO pomodoro_sessions (task_id, started_at, ended_at, duration_minutes, notes, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    int(task_id) if task_id is not None else None,
                    started_at.isoformat(timespec="seconds"),
                    ended_at.isoformat(timespec="seconds"),
                    int(duration_minutes),
                    notes or "",
                ),
            )
    except Exception as ex:
        toast_warning(f"Failed to log session: {ex}")


def _transition_to_next(cfg: PomodoroConfig, state: PomodoroState) -> None:
    """Advance to next mode and notify."""
    if state.mode == "focus":
        # A focus ended
        state.total_focus_completed += 1
        state.cycle_count += 1
        # Long break if interval reached
        if cfg.long_break_interval > 0 and state.cycle_count % cfg.long_break_interval == 0:
            state.mode = "long_break"
            state.time_left_sec = max(1, cfg.long_break_minutes * 60)
            notify_placeholder("Long break time!", "Great job. Take a longer rest.")
        else:
            state.mode = "short_break"
            state.time_left_sec = max(1, cfg.short_break_minutes * 60)
            notify_placeholder("Short break time!", "Breathe. Hydrate. Stretch.")
    else:
        # Break ended -> back to focus
        state.mode = "focus"
        state.time_left_sec = max(1, cfg.focus_minutes * 60)
        notify_placeholder("Focus time", "Back to work. You got this!")


def _complete_current_interval_and_log(state: PomodoroState) -> None:
    """Persist completed interval (focus/break) if meaningful."""
    if not state.current_session_start:
        return
    start = state.current_session_start
    end = _now()
    # Only log completed focus sessions and breaks >= 1 minute
    dur_minutes = max(1, int((end - start).total_seconds() // 60))
    note = f"{state.mode} completed"
    # For logs, we want to log the interval that just ended. But we call this when time_left reaches 0
    # The 'state.mode' is still the old mode that just finished at the tick boundary.
    try:
        _persist_session(state.bound_task_id, start, end, dur_minutes, note)
    finally:
        state.current_session_start = None


def _start_new_interval_clock(state: PomodoroState) -> None:
    """Mark the start timestamp for logging."""
    state.current_session_start = _now()


def _tick_once() -> None:
    """Perform one second of ticking safely."""
    cfg, state = _ensure_session_state()
    if not state.is_running:
        return
    # decrement
    if state.time_left_sec > 0:
        state.time_left_sec -= 1
        if state.time_left_sec == 0:
            # End of the interval
            # Log just-finished period
            _complete_current_interval_and_log(state)
            # Transition
            prev_mode = state.mode
            _transition_to_next(cfg, state)
            # Start timing for the new period automatically
            _start_new_interval_clock(state)
            # Toasts for UI
            if prev_mode == "focus":
                toast_success("Focus session complete! Break started.")
            else:
                toast_info("Break complete. Focus started.")
    else:
        # Safety
        state.time_left_sec = 0


def _ticker_loop() -> None:
    """Background ticker loop. Persists across Streamlit reruns but single per process."""
    while not _ticker_stop.is_set():
        try:
            _tick_once()
        except Exception:
            # We avoid crashing the ticker on UI exceptions
            pass
        finally:
            # Wait 1 second or until stop signaled
            if _ticker_stop.wait(timeout=1.0):
                break


# PUBLIC_INTERFACE
def start_ticker_once() -> None:
    """Start a single background ticker thread once per process."""
    global _ticker_thread
    with _ticker_lock:
        if _ticker_thread and _ticker_thread.is_alive():
            return
        _ticker_stop.clear()
        _ticker_thread = threading.Thread(target=_ticker_loop, name="PomodoroTicker", daemon=True)
        _ticker_thread.start()


# PUBLIC_INTERFACE
def stop_ticker() -> None:
    """Stop ticker thread. Not typically called in Streamlit runtime."""
    global _ticker_thread
    with _ticker_lock:
        if _ticker_thread and _ticker_thread.is_alive():
            _ticker_stop.set()
            _ticker_thread.join(timeout=3)
            _ticker_thread = None


# PUBLIC_INTERFACE
def start_timer(bound_task_id: Optional[int] = None) -> None:
    """Start/resume the timer, binding to a task if provided."""
    cfg, state = _ensure_session_state()
    if not state.is_running:
        state.is_running = True
        if state.current_session_start is None:
            _start_new_interval_clock(state)
        if bound_task_id is not None:
            try:
                state.bound_task_id = int(bound_task_id)
            except Exception:
                state.bound_task_id = None
        toast_info("Timer started.")
    start_ticker_once()


# PUBLIC_INTERFACE
def pause_timer() -> None:
    """Pause the timer without resetting the remaining time."""
    _, state = _ensure_session_state()
    if state.is_running:
        state.is_running = False
        toast_info("Timer paused.")


# PUBLIC_INTERFACE
def reset_timer() -> None:
    """Reset to start of current mode and clear current interval unlogged if short (<1m)."""
    cfg, state = _ensure_session_state()
    state.is_running = False
    # Discard partial interval if <60s
    if state.current_session_start:
        elapsed = int((_now() - state.current_session_start).total_seconds())
        if elapsed >= 60:
            # Log partial if ≥ 1m
            _complete_current_interval_and_log(state)
        else:
            state.current_session_start = None
    # Reset time to full length for current mode
    if state.mode == "focus":
        state.time_left_sec = cfg.focus_minutes * 60
    elif state.mode == "short_break":
        state.time_left_sec = cfg.short_break_minutes * 60
    else:
        state.time_left_sec = cfg.long_break_minutes * 60
    toast_warning("Timer reset.")


# PUBLIC_INTERFACE
def apply_config(focus: int, short: int, long: int, interval: int) -> None:
    """Update configuration and reset the current mode's time budget only if not running."""
    focus = max(1, int(focus))
    short = max(1, int(short))
    long = max(1, int(long))
    interval = max(1, int(interval))
    cfg, state = _ensure_session_state(PomodoroConfig(focus, short, long, interval))
    # If not running, reset time_left for current mode
    if not state.is_running:
        if state.mode == "focus":
            state.time_left_sec = cfg.focus_minutes * 60
        elif state.mode == "short_break":
            state.time_left_sec = cfg.short_break_minutes * 60
        else:
            state.time_left_sec = cfg.long_break_minutes * 60


# PUBLIC_INTERFACE
def switch_mode(new_mode: str) -> None:
    """Force switch modes (focus/short_break/long_break) and reset timer for that mode."""
    cfg, state = _ensure_session_state()
    if new_mode not in ("focus", "short_break", "long_break"):
        return
    state.is_running = False
    # Log partial if meaningful
    if state.current_session_start:
        elapsed = int((_now() - state.current_session_start).total_seconds())
        if elapsed >= 60:
            _complete_current_interval_and_log(state)
        state.current_session_start = None
    state.mode = new_mode
    if new_mode == "focus":
        state.time_left_sec = cfg.focus_minutes * 60
    elif new_mode == "short_break":
        state.time_left_sec = cfg.short_break_minutes * 60
    else:
        state.time_left_sec = cfg.long_break_minutes * 60
    toast_info(f"Switched to {new_mode.replace('_',' ').title()}.")


# PUBLIC_INTERFACE
def get_config_and_state() -> Tuple[PomodoroConfig, PomodoroState]:
    """Return current config and state."""
    return _ensure_session_state()


# PUBLIC_INTERFACE
def format_time_left(seconds: int) -> str:
    """Format remaining seconds as MM:SS."""
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"


# PUBLIC_INTERFACE
def list_recent_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent pomodoro sessions for history display."""
    with db.get_cursor() as cur:
        cur.execute(
            """
            SELECT ps.id, ps.task_id, ps.started_at, ps.ended_at, ps.duration_minutes, ps.notes,
                   COALESCE(t.title,'') as task_title
            FROM pomodoro_sessions ps
            LEFT JOIN tasks t ON ps.task_id = t.id
            ORDER BY ps.started_at DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        return [dict(r) for r in cur.fetchall()]
