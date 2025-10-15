import threading
from datetime import datetime
from typing import Optional

from . import db
from .utils import log, notify_placeholder


# Process-wide guard and runtime config
_scheduler_lock = threading.Lock()
_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_config_lock = threading.Lock()
_interval_seconds: int = 60
_notifications_enabled: bool = True


def _loop() -> None:
    """Background loop scanning for reminders."""
    log("Scheduler loop started.")
    while not _stop_event.is_set():
        try:
            now_iso = datetime.now().isoformat(timespec="seconds")
            # Fetch due reminders
            due = db.get_due_unsent_reminders(now_iso=now_iso)
            if due:
                log(f"Found {len(due)} due reminders.")
            with _config_lock:
                do_notify = _notifications_enabled
                interval = _interval_seconds

            for r in due:
                if do_notify:
                    notify_placeholder(
                        title="Reminder Due",
                        body=f"Task: {r.get('title') or 'Untitled'} at {r.get('remind_at')}",
                    )
                db.mark_reminder_sent(reminder_id=int(r["id"]))
        except Exception as ex:
            log(f"Scheduler error: {ex}")
        finally:
            # Sleep using current interval
            with _config_lock:
                interval = _interval_seconds
            _stop_event.wait(timeout=max(5, int(interval)))
    log("Scheduler loop stopped.")


# PUBLIC_INTERFACE
def start_scheduler_once(interval_seconds: int = 60, notifications_enabled: bool = True) -> None:
    """Start the scheduler loop in a daemon thread once per process."""
    global _scheduler_thread, _interval_seconds, _notifications_enabled
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            # Update config only
            update_scheduler_config(interval_seconds, notifications_enabled)
            return

        _interval_seconds = int(interval_seconds)
        _notifications_enabled = bool(notifications_enabled)
        _stop_event.clear()
        _scheduler_thread = threading.Thread(target=_loop, name="ReminderScheduler", daemon=True)
        _scheduler_thread.start()
        log("Scheduler thread started.")


# PUBLIC_INTERFACE
def update_scheduler_config(interval_seconds: Optional[int] = None, notifications_enabled: Optional[bool] = None) -> None:
    """Update scheduler runtime configuration in a threadsafe manner."""
    global _interval_seconds, _notifications_enabled
    with _config_lock:
        if interval_seconds is not None:
            _interval_seconds = int(interval_seconds)
        if notifications_enabled is not None:
            _notifications_enabled = bool(notifications_enabled)
    log(f"Scheduler config updated: interval={_interval_seconds}s, notifications={_notifications_enabled}")


# PUBLIC_INTERFACE
def stop_scheduler() -> None:
    """Signal the scheduler to stop. Mainly for tests or controlled shutdowns."""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            _stop_event.set()
            _scheduler_thread.join(timeout=5)
            _scheduler_thread = None
            log("Scheduler stopped.")
