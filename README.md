# student-task-scheduler-and-reminder-176128-176137

This repository includes:
- task_scheduler_backend (FastAPI) for health and future APIs.
- streamlit_app (Streamlit) UI for the Task Scheduler & Reminder App.

Quick start (Streamlit UI):

1) Install dependencies (base image may already include Streamlit):
   - pip install -r task_scheduler_backend/requirements.txt
   - pip install streamlit schedule python-dotenv

2) Optional: copy .env.example to .env in task_scheduler_backend and adjust.
   - cp task_scheduler_backend/.env.example task_scheduler_backend/.env

3) Run Streamlit:
   - cd task_scheduler_backend
   - streamlit run streamlit_app/app.py

Features in this vertical slice:
- Automatic SQLite database initialization on first run (tables: categories, tasks, reminders, pomodoro_sessions, settings)
- Safe background scheduler thread (guarded, non-duplicating across reruns)
- Ocean Professional-themed UI skeleton with sidebar navigation (Dashboard, Tasks, Pomodoro, Settings)
- Basic settings toggles and non-blocking toasts/logs
- Modular code ready for further development