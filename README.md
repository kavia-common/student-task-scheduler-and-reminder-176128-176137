# student-task-scheduler-and-reminder-176128-176137

## Project overview and goals
This project delivers a Streamlit-based Task Scheduler & Reminder app designed for students and procrastinators to manage daily tasks, study sessions, and coding practice efficiently. It combines a simple local SQLite database, a guarded background scheduler for reminders, a suggestion engine for “what to do next,” and a Pomodoro timer with logging. A minimal FastAPI backend is included for health checks today and to host future APIs.

Primary goals:
- Provide an approachable, single-user task manager with recurrence, due dates, and priorities.
- Surface helpful analytics and suggestions to reduce decision fatigue.
- Offer focus support via an integrated Pomodoro with basic history logging.
- Prepare a path to future multi-user and API-driven features via FastAPI.

## Architecture and module map
Container: task_scheduler_backend

- streamlit_app/app.py
  - Streamlit entrypoint and UI composition.
  - Initializes database and guarded scheduler once per process.
  - Sidebar navigation: Dashboard, Tasks, Pomodoro, Settings.
  - Wires live configuration controls for scheduler and suggestions.

- streamlit_app/db.py
  - SQLite data access and schema initialization.
  - Thread-local connections, foreign keys enabled.
  - CRUD for tasks, category management, reminder alignment with due dates.
  - Aggregations for dashboard KPIs and counts.

- streamlit_app/scheduler.py
  - Background daemon thread scanning reminders at a configurable interval.
  - Global guards to ensure a single thread per process, even across Streamlit reruns.
  - Thread-safe config updates for interval and notifications.

- streamlit_app/dashboards.py
  - Analytics helpers and dataframes for KPIs, completion trends, tasks-by-category, and priority distribution.
  - Filter model that converts date filters into SQL-friendly ranges.

- streamlit_app/pomodoro.py
  - Pomodoro config and state stored in Streamlit session_state.
  - Single background ticker thread guarded per process.
  - Mode transitions (focus, short_break, long_break) with notifications and history persisted to DB.

- streamlit_app/suggestion.py
  - Heuristic suggestion engine scoring tasks by priority, urgency, overdue boost, and short-task bias.
  - Optional time-slot penalty when user specifies available minutes.

- streamlit_app/utils.py
  - Ocean Professional styling injection.
  - Toast helpers, in-app logging, OS notification attempt via plyer with in-app fallback.
  - Simple confirmation helper.

- streamlit_app/settings.py
  - Settings dataclass and singleton loader from environment variables.
  - Weights and intervals overridable via env.

- src/api/main.py (FastAPI)
  - Minimal FastAPI app providing a health-check endpoint at “/” with permissive CORS.
  - Intended foundation for future task/reminder APIs.

## Database schema and initialization
On first run, the app creates an SQLite database at DATA_DIR/app.db (DATA_DIR is configurable via env). Schema highlights:
- categories
  - id INTEGER PK, name TEXT UNIQUE NOT NULL
- tasks
  - id INTEGER PK
  - title TEXT NOT NULL, description TEXT, category_id FK
  - priority INTEGER DEFAULT 2 (1=Low, 2=Medium, 3=High)
  - estimated_minutes INTEGER DEFAULT 0
  - due_datetime TEXT (ISO 8601)
  - status TEXT DEFAULT 'open' (open, in_progress, done, canceled)
  - recurrence TEXT DEFAULT 'none' (none, daily, weekly, monthly)
  - recurrence_end_date TEXT (ISO date)
  - completed INTEGER DEFAULT 0
  - created_at/updated_at TEXT
  - Indices: due_datetime, status, priority
- reminders
  - id INTEGER PK
  - task_id FK, remind_at TEXT, sent INTEGER DEFAULT 0
  - Indices: remind_at, sent
- pomodoro_sessions
  - id INTEGER PK
  - task_id FK (nullable), started_at TEXT, ended_at TEXT
  - duration_minutes INTEGER, notes TEXT, created_at TEXT
- settings
  - key TEXT PRIMARY KEY, value TEXT

Initialization model:
- db.init_db() runs once per process using a lock. Subsequent calls are no-ops.
- Thread-local SQLite connections are used to avoid cross-thread issues; foreign keys are enforced.

## Scheduling and notifications
- A background scheduler thread (scheduler.start_scheduler_once) is started from the Streamlit app after initialization and guarded to avoid duplicates on reruns.
- The loop checks db.get_due_unsent_reminders(now_iso) and triggers notifications for each due reminder.
- Notifications:
  - Primary attempt: OS-level notification via plyer (if available).
  - Fallback: in-app Streamlit toasts, always visible if plyer is unavailable or fails.
- Interval and enablement:
  - Configurable at runtime via sidebar/Settings and via env.
  - Thread-safe update via scheduler.update_scheduler_config.
- Sleep and responsiveness:
  - The loop sleeps for the configured interval (minimum 5 seconds), but configuration can be updated at runtime.
- Fallbacks:
  - If notifications are disabled, reminders are still marked as sent when due are processed, but no user notification is fired.
  - Logging appears in the sidebar via utils.log for visibility.

## Features guide
### Tasks CRUD and recurrence
- Create, edit, delete tasks with title, description, optional category, priority (Low/Medium/High), estimated minutes, due date/time, status, and recurrence pattern (none/daily/weekly/monthly) with an end date.
- When setting or updating a due date/time, an initial reminder is aligned to that due datetime. If a reminder exists and is unsent, it is updated; otherwise, a new reminder is created.
- “Start now” sets status to in_progress. From the Tasks page, you can optionally start a Pomodoro bound to that task.

### Dashboard and analytics
- KPIs: total, pending, completed today, completed this week, and overdue counts.
- Charts:
  - Completion Trend (Altair area chart)
  - Tasks by Category (Altair bar)
  - Priority Distribution (Plotly pie)
- Filters for date range, category, and status affect KPIs and charts.

### Pomodoro
- Configurable durations (focus, short break, long break) and long-break interval.
- Single guarded ticker thread that advances every second and transitions automatically between modes.
- Notifications when moving between focus and breaks.
- Optionally bind sessions to a selected task. Completed intervals (>=1 minute) are logged to the pomodoro_sessions table. Quick mode switching and reset controls are provided.

### Suggestions
- Heuristic ranking combines:
  - Priority normalization (High > Medium > Low)
  - Urgency to due date within a configurable window
  - Overdue boost
  - Short-task bias based on an estimated-minute threshold
- If you provide an available time slot (minutes), longer tasks receive a soft penalty so short tasks float to the top.

## Configuration
Create a .env file in task_scheduler_backend (optional) to override defaults. Example keys:

- NOTIFICATIONS_ENABLED=true|false
- SCHEDULER_INTERVAL_SECONDS=60
- DATA_DIR=./data
- SUGGESTION_WEIGHT_PRIORITY=1.0
- SUGGESTION_WEIGHT_URGENCY=1.0
- SUGGESTION_WEIGHT_OVERDUE_BOOST=1.0
- SUGGESTION_WEIGHT_SHORT_TASK_BIAS=0.5
- SUGGESTION_SHORT_TASK_THRESHOLD_MIN=30
- SUGGESTION_URGENCY_WINDOW_HOURS=72
- POMODORO_FOCUS_MINUTES=25
- POMODORO_SHORT_BREAK_MINUTES=5
- POMODORO_LONG_BREAK_MINUTES=15
- POMODORO_LONG_BREAK_INTERVAL=4

How overrides apply:
- Settings are loaded via streamlit_app/settings.py at app startup.
- Suggestion weights can be adjusted live in Settings; these updates affect the current session. To persist across restarts, set the corresponding environment variables.
- Pomodoro defaults can also be read from env on first initialization of session state.

## Running the app
1) Install dependencies (includes Streamlit, charts, FastAPI, plyer):
   - pip install -r task_scheduler_backend/requirements.txt

2) Optional: create a .env at task_scheduler_backend/.env with keys listed above.

3) Launch Streamlit UI:
   - cd task_scheduler_backend
   - streamlit run streamlit_app/app.py

Notes on running alongside the backend:
- The FastAPI app is currently a minimal health-check service. If you want to preview it:
  - uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
- The Streamlit UI does not yet depend on FastAPI endpoints; it accesses SQLite directly. Future integration will move data access behind APIs.

## Manual validation checklist
- First launch:
  - App creates the ./data directory and app.db under DATA_DIR.
  - No duplicate scheduler threads; logs display “Scheduler thread started.”
- Tasks:
  - Create a task with a due date/time. Confirm a reminder row is created or updated.
  - Edit the task’s due date/time. Confirm the reminder alignments update.
  - Use search, status, category, and date filters; verify the list changes as expected.
- Suggestions:
  - Create tasks with varied priorities and due dates. Provide a time slot in the Dashboard/Tasks pages and confirm suggestions reflect urgency/priority and soft penalties.
- Dashboard:
  - Complete a task (set status=done). Verify KPIs update and charts show trend entries on the current day/week.
- Pomodoro:
  - Start a focus session, let it elapse or fast-forward by reducing durations and watch automatic transitions. Verify sessions >=1 minute log into the database. Bind a task and see titles in history.
- Notifications and scheduler:
  - Set a reminder in the near future and verify a toast/notification fires when due. Toggle notifications off and confirm no pop-up occurs, while reminders still mark as sent.
- Settings:
  - Adjust scheduler interval and suggestion weights from Settings or sidebar and ensure runtime effects are visible.

## Troubleshooting tips
- If notifications do not appear:
  - plyer may not be available on your OS or in headless environments; in-app toasts will still display.
  - Ensure NOTIFICATIONS_ENABLED=true and the scheduler is running (check sidebar log messages).
- If charts are empty:
  - Create tasks and mark some as done; charts visualize actual data.
- If scheduler seems inactive:
  - Verify SCHEDULER_INTERVAL_SECONDS and sidebar interval matches expectation.
  - Check sidebar logs for “Scheduler loop started” or errors.
- Database path:
  - DB is created at DATA_DIR/app.db. Ensure DATA_DIR points to a writeable folder.

## Future work
- FastAPI integration:
  - Replace direct SQLite calls from Streamlit with REST endpoints for tasks, reminders, and pomodoro sessions.
  - Add authentication and multi-user data partitioning.
  - Provide endpoints for suggestions and analytics to support other clients.
- Multi-user considerations:
  - Move from local SQLite to a centralized database (e.g., PostgreSQL).
  - Introduce per-user schemas or tenant IDs; ensure permission checks in APIs.
  - Rework scheduler from per-process thread to a centralized worker or distributed job queue.
- Advanced features:
  - Natural-language quick-add, calendar integrations, and smarter recurrence generation.
  - Push notifications via web or mobile channels.

## Quick start (condensed)
- pip install -r task_scheduler_backend/requirements.txt
- Optional: create task_scheduler_backend/.env with overrides.
- cd task_scheduler_backend && streamlit run streamlit_app/app.py

## Notes
- Theme: “Ocean Professional” applied via utils.ocean_styles with blue/amber accents.
- Current FastAPI is a health check only; app logic resides in Streamlit modules for this slice.