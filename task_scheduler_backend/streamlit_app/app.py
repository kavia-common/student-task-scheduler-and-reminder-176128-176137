import streamlit as st
from datetime import datetime, date
from typing import Optional

import altair as alt
import plotly.express as px

from . import db
from . import scheduler as sched
from .settings import get_settings, Settings
from .utils import ocean_styles, toast_info, toast_success, toast_warning, format_ts
from .dashboards import (
    DashboardFilters,
    get_kpis,
    completion_trend_dataframe,
    tasks_by_category_dataframe,
    priority_distribution_dataframe,
)


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

    # Filters row
    with st.container():
        cf1, cf2, cf3, cf4 = st.columns([1.2, 1.2, 1.2, 1.2])
        with cf1:
            # Date range
            dr = st.date_input("Date range (due date)", [], help="Filter analytics by due date range.")
            start_d: Optional[date] = None
            end_d: Optional[date] = None
            if isinstance(dr, list) and len(dr) == 2 and (dr[0] or dr[1]):
                start_d = dr[0] or None
                end_d = dr[1] or None
        with cf2:
            categories = ["any"] + db.list_categories()
            sel_cat = st.selectbox("Category", options=categories, index=0)
        with cf3:
            sel_status = st.selectbox("Status", options=["any","open","in_progress","done","canceled"], index=0)
        with cf4:
            st.caption("Use filters to refine KPIs and charts.")

    filters = DashboardFilters(
        start_date=start_d,
        end_date=end_d,
        category=sel_cat,
        status=sel_status,
    )

    # KPI row
    kpis = get_kpis(filters)
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.metric("Total Tasks", kpis.get("total", 0))
    with k2:
        st.metric("Pending", kpis.get("pending", 0))
    with k3:
        st.metric("Completed Today", kpis.get("completed_today", 0))
    with k4:
        st.metric("This Week", kpis.get("completed_this_week", 0))
    with k5:
        st.metric("Overdue", kpis.get("overdue", 0))

    # Secondary quick stats
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Open Tasks (all)", db.count_open_tasks())
    with c2:
        st.metric("Due Today (all)", db.count_due_today())
    with c3:
        st.metric("Pomodoro Sessions Today", db.count_pomodoro_today())

    st.markdown("---")

    # Charts
    ch1, ch2 = st.columns([2, 1.5])

    # Completion trend (Altair line/area chart)
    with ch1:
        st.subheader("Completion Trend")
        df_trend = completion_trend_dataframe(filters)
        if df_trend.empty:
            st.info("No completion data for the selected filters/date range.")
        else:
            chart = (
                alt.Chart(df_trend)
                .mark_area(line={"color": "#2563EB"}, color="lightblue", opacity=0.5)
                .encode(
                    x=alt.X("day:T", title="Day"),
                    y=alt.Y("completed_count:Q", title="Completed Tasks"),
                    tooltip=[alt.Tooltip("day:T", title="Day"), alt.Tooltip("completed_count:Q", title="Completed")],
                )
                .properties(height=300)
            )
            st.altair_chart(chart, use_container_width=True)

    # Tasks by category (Altair bar)
    with ch2:
        st.subheader("Tasks by Category")
        df_cat = tasks_by_category_dataframe(filters)
        if df_cat.empty:
            st.info("No tasks found for the selected filters.")
        else:
            chart2 = (
                alt.Chart(df_cat)
                .mark_bar(color="#2563EB")
                .encode(
                    x=alt.X("cnt:Q", title="Count"),
                    y=alt.Y("category:N", sort="-x", title="Category"),
                    tooltip=[alt.Tooltip("category:N", title="Category"), alt.Tooltip("cnt:Q", title="Tasks")],
                )
                .properties(height=300)
            )
            st.altair_chart(chart2, use_container_width=True)

    # Priority distribution (Plotly pie)
    st.subheader("Priority Distribution")
    df_pri = priority_distribution_dataframe(filters)
    if df_pri.empty:
        st.info("No tasks to show priority distribution for the selected filters.")
    else:
        # Map priority numbers to labels
        def pri_label(n: int) -> str:
            try:
                i = int(n)
            except Exception:
                return "Unknown"
            return {3: "High", 2: "Medium", 1: "Low"}.get(i, f"P{i}")

        df_pri = df_pri.copy()
        df_pri["priority_label"] = df_pri["priority"].apply(pri_label)
        fig = px.pie(df_pri, values="cnt", names="priority_label", color="priority_label",
                     color_discrete_map={"High": "#EF4444", "Medium": "#F59E0B", "Low": "#10B981"})
        fig.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(fig, use_container_width=True)


def page_tasks() -> None:
    st.markdown("### ✅ Tasks")

    # Filters
    with st.container():
        colf1, colf2, colf3, colf4, colf5 = st.columns([1.3,1,1,1.6,1.3])
        with colf1:
            status = st.selectbox("Status", options=["any","open","in_progress","done","canceled"], index=0)
        with colf2:
            categories = ["any"] + db.list_categories()
            category = st.selectbox("Category", options=categories, index=0)
        with colf3:
            priority_min = st.select_slider("Min Priority", options=[1,2,3], value=1, help="1=Low, 2=Med, 3=High")
        with colf4:
            date_range = st.date_input("Due date range", [])
        with colf5:
            search = st.text_input("Search", "")

    # Create/Edit form
    st.markdown("#### Add / Edit Task")
    if "edit_task_id" not in st.session_state:
        st.session_state["edit_task_id"] = None

    editing = st.session_state["edit_task_id"] is not None
    existing = db.get_task(st.session_state["edit_task_id"]) if editing else None

    with st.form("task_form", clear_on_submit=not editing):
        col1, col2 = st.columns(2)
        with col1:
            title = st.text_input("Title*", value=(existing["title"] if existing else ""))
            category_name = st.text_input("Category", value=(existing["category"] if existing else ""))
            priority_label_to_val = {"High":3, "Medium":2, "Low":1}
            inv_map = {1:"Low",2:"Medium",3:"High"}
            priority_init = inv_map.get(int(existing["priority"])) if existing and existing.get("priority") is not None else "Medium"
            priority_label = st.selectbox("Priority", options=["High","Medium","Low"], index=["High","Medium","Low"].index(priority_init))
            est = st.number_input("Estimated minutes", min_value=0, step=5, value=int(existing["estimated_minutes"]) if existing and existing.get("estimated_minutes") is not None else 0)
        with col2:
            status_val = st.selectbox("Status", options=["open","in_progress","done","canceled"], index=(["open","in_progress","done","canceled"].index(existing["status"]) if existing else 0))
            recurrence = st.selectbox("Recurrence", options=["none","daily","weekly","monthly"], index=(["none","daily","weekly","monthly"].index(existing["recurrence"]) if existing else 0))
            rec_end = st.date_input("Recurrence end date", value=(None if not existing or not existing.get("recurrence_end_date") else datetime.fromisoformat(existing["recurrence_end_date"])))  # type: ignore
        description = st.text_area("Description", value=(existing["description"] if existing else ""))

        # Due date and time
        coldt1, coldt2 = st.columns(2)
        if existing and existing.get("due_datetime"):
            try:
                eddt = datetime.fromisoformat(existing["due_datetime"])
                due_date = st.date_input("Due date", value=eddt.date())
                due_time = st.time_input("Due time", value=eddt.time().replace(second=0, microsecond=0))
            except Exception:
                due_date = st.date_input("Due date", value=None)
                due_time = st.time_input("Due time", value=None)
        else:
            due_date = st.date_input("Due date", value=None)
            due_time = st.time_input("Due time", value=None)

        submitted = st.form_submit_button("Update Task" if editing else "Create Task")
        if submitted:
            # validation
            if not title or not title.strip():
                toast_warning("Title is required.")
            elif est is not None and est < 0:
                toast_warning("Estimated minutes must be >= 0.")
            else:
                due_iso = None
                if due_date and due_time:
                    due_iso = datetime.combine(due_date, due_time).isoformat(timespec="minutes")
                elif due_date and not due_time:
                    # default time 09:00
                    due_iso = datetime.combine(due_date, datetime.strptime("09:00", "%H:%M").time()).isoformat(timespec="minutes")

                rec_end_iso = rec_end.isoformat() if rec_end else None
                try:
                    if editing and existing:
                        db.update_task(
                            task_id=int(existing["id"]),
                            title=title,
                            description=description,
                            category_name=category_name,
                            priority=int(priority_label_to_val[priority_label]),
                            estimated_minutes=int(est or 0),
                            due_datetime=due_iso,
                            status=status_val,
                            recurrence=recurrence,
                            recurrence_end_date=rec_end_iso,
                        )
                        st.session_state["edit_task_id"] = None
                        toast_success("Task updated.")
                    else:
                        db.create_task(
                            title=title,
                            description=description,
                            category_name=category_name,
                            priority=int(priority_label_to_val[priority_label]),
                            estimated_minutes=int(est or 0),
                            due_datetime=due_iso,
                            status=status_val,
                            recurrence=recurrence,
                            recurrence_end_date=rec_end_iso,
                        )
                        toast_success("Task created.")
                except Exception as ex:
                    st.error(f"Failed to save task: {ex}")

    st.markdown("#### Task List")
    # prepare date_range tuple
    dr_tuple = None
    if isinstance(date_range, list) and len(date_range) == 2:
        start = date_range[0].isoformat() if date_range[0] else None
        end = date_range[1].isoformat() if date_range[1] else None
        if start or end:
            dr_tuple = (start or "", end or "")
    elif not date_range:
        dr_tuple = None

    tasks = db.list_tasks(
        limit=500,
        status=status,
        category=category,
        priority_min=priority_min,
        priority_max=3,
        date_range=dr_tuple,
        search=search,
    )

    if not tasks:
        st.caption("No tasks found.")
    else:
        for t in tasks:
            with st.container():
                cols = st.columns([0.05, 0.35, 0.2, 0.2, 0.2])
                with cols[0]:
                    st.write("✅" if t.get("completed") else "⬜")
                with cols[1]:
                    st.write(f"{t['title']}  \n{t.get('description','')}")
                    meta = []
                    if t.get("category"):
                        meta.append(f"📁 {t['category']}")
                    meta.append(f"🔼 P{int(t.get('priority') or 0)}")
                    if t.get("estimated_minutes") is not None:
                        meta.append(f"⏱️ {int(t['estimated_minutes'])}m")
                    if t.get("due_datetime"):
                        meta.append(f"🕒 {format_ts(t['due_datetime'])}")
                    st.caption(" • ".join(meta))
                with cols[2]:
                    st.caption(f"Status: {t.get('status')}")
                    st.caption(f"Recurrence: {t.get('recurrence')}")
                with cols[3]:
                    if st.button("Edit", key=f"edit_{t['id']}"):
                        st.session_state["edit_task_id"] = int(t["id"])
                        st.experimental_rerun()
                with cols[4]:
                    if st.button("Delete", type="primary", key=f"del_{t['id']}"):
                        try:
                            db.delete_task(int(t["id"]))
                            toast_success("Task deleted.")
                            st.experimental_rerun()
                        except Exception as ex:
                            st.error(f"Failed to delete: {ex}")


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
