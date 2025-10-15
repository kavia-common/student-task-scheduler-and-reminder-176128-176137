import streamlit as st

from . import db
from . import scheduler as sched
from .settings import get_settings, Settings
from .utils import ocean_styles, toast_info, toast_success


# PUBLIC_INTERFACE
def init_app_state() -> None:
    """Initialize Streamlit session state for navigation and one-time setups."""
    if "nav" not in st.session_state:
        st.session_state["nav"] = "Dashboard"
    if "initialized" not in st.session_state:
        st.session_state["initialized"] = False


def ensure_db_initialized() -> None:
    """Ensure the SQLite database and schema are initialized exactly once per process."""
    try:
        db.init_db()
    except Exception as ex:
        st.error(f"Database initialization failed: {ex}")


def ensure_scheduler_running(settings: Settings) -> None:
    """
    Start the background scheduler thread safely.
    - Guarded so it won't duplicate across Streamlit reruns.
    - Non-blocking, responds to settings.
    """
    try:
        sched.start_scheduler_once(
            interval_seconds=settings.SCHEDULER_INTERVAL_SECONDS,
            notifications_enabled=settings.NOTIFICATIONS_ENABLED,
        )
    except Exception as ex:
        st.warning(f"Scheduler could not start: {ex}")


def render_sidebar(settings: Settings) -> None:
    """Render the sidebar navigation and settings toggles."""
    with st.sidebar:
        st.markdown("## 📘 Task Scheduler")
        st.markdown("Manage tasks, reminders, and focus sessions.")

        nav = st.radio(
            "Navigate",
            options=["Dashboard", "Tasks", "Pomodoro", "Settings"],
            index=["Dashboard", "Tasks", "Pomodoro", "Settings"].index(st.session_state["nav"]),
        )
        st.session_state["nav"] = nav

        st.markdown("---")
        st.caption("Theme: Ocean Professional")

        # Quick settings toggles
        st.markdown("#### Quick Settings")
        notif = st.toggle(
            "Enable Notifications",
            value=settings.NOTIFICATIONS_ENABLED,
            help="Turn reminder notifications on/off. Placeholders shown in UI.",
        )
        interval = st.slider(
            "Scheduler Interval (seconds)",
            min_value=15,
            max_value=300,
            value=settings.SCHEDULER_INTERVAL_SECONDS,
            step=15,
            help="How often background scheduler scans for due reminders.",
        )

        # Update runtime settings and scheduler parameters live.
        if notif != settings.NOTIFICATIONS_ENABLED or interval != settings.SCHEDULER_INTERVAL_SECONDS:
            # Update in-memory settings
            settings.NOTIFICATIONS_ENABLED = bool(notif)
            settings.SCHEDULER_INTERVAL_SECONDS = int(interval)

            # Apply to scheduler
            try:
                sched.update_scheduler_config(
                    interval_seconds=settings.SCHEDULER_INTERVAL_SECONDS,
                    notifications_enabled=settings.NOTIFICATIONS_ENABLED,
                )
                toast_success("Scheduler settings updated.")
            except Exception as ex:
                st.warning(f"Failed to update scheduler config: {ex}")


def page_dashboard() -> None:
    st.markdown("### 📊 Dashboard")
    st.write("Welcome! Your upcoming reminders and stats will appear here.")
    # Placeholder summary cards
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Open Tasks", db.count_open_tasks())
    with col2:
        st.metric("Due Today", db.count_due_today())
    with col3:
        st.metric("Pomodoro Sessions", db.count_pomodoro_today())

    st.info("This is a minimal vertical slice. More insights coming soon.")


def page_tasks() -> None:
    st.markdown("### ✅ Tasks")
    st.write("Create and manage tasks. (Placeholder UI)")

    with st.expander("Add Task"):
        title = st.text_input("Title", "")
        description = st.text_area("Description", "")
        category = st.text_input("Category", "")
        due_date = st.date_input("Due Date (optional)")
        if st.button("Add Task"):
            try:
                db.add_task(title=title, description=description, category_name=category, due_date=due_date)
                toast_success("Task added.")
            except Exception as ex:
                st.error(f"Failed to add task: {ex}")

    st.markdown("#### Tasks")
    tasks = db.list_tasks(limit=20)
    if not tasks:
        st.caption("No tasks yet.")
    else:
        for t in tasks:
            st.write(f"- [{ 'x' if t['completed'] else ' '}] {t['title']} (Category: {t.get('category','-')})")


def page_pomodoro() -> None:
    st.markdown("### 🍅 Pomodoro")
    st.write("Focus timer and session logging. (Placeholder UI)")
    st.caption("Use this page to start a focus session and log results. Coming soon.")


def page_settings(settings: Settings) -> None:
    st.markdown("### ⚙️ Settings")
    st.write("Configure your app preferences.")

    st.text_input("Database Path", value=db.get_db_path(), disabled=True, help="Using local SQLite database.")
    st.toggle("Notifications Enabled", value=settings.NOTIFICATIONS_ENABLED, disabled=True)
    st.slider("Scheduler Interval Seconds", 15, 300, settings.SCHEDULER_INTERVAL_SECONDS, disabled=True)

    st.caption("Environment variables can override defaults. See .env.example.")


def render_main(nav: str, settings: Settings) -> None:
    if nav == "Dashboard":
        page_dashboard()
    elif nav == "Tasks":
        page_tasks()
    elif nav == "Pomodoro":
        page_pomodoro()
    elif nav == "Settings":
        page_settings(settings)
    else:
        st.write("Unknown page.")


def main() -> None:
    """Streamlit app entry point."""
    st.set_page_config(
        page_title="Task Scheduler & Reminders",
        page_icon="📘",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    ocean_styles(primary="#2563EB", secondary="#F59E0B")

    init_app_state()

    settings = get_settings()

    # Initialize DB and Scheduler once per process
    ensure_db_initialized()
    ensure_scheduler_running(settings)

    render_sidebar(settings)
    render_main(st.session_state["nav"], settings)

    if not st.session_state["initialized"]:
        st.session_state["initialized"] = True
        toast_info("App initialized.")


if __name__ == "__main__":
    main()
