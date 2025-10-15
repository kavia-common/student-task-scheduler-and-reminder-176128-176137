import streamlit as st
from datetime import datetime
from typing import Optional


def ocean_styles(primary: str = "#2563EB", secondary: str = "#F59E0B") -> None:
    """Inject basic Ocean Professional theme touches."""
    st.markdown(
        f"""
        <style>
            :root {{
                --primary: {primary};
                --secondary: {secondary};
            }}
            .stApp {{
                background-color: #f9fafb;
            }}
            .block-container {{
                padding-top: 2rem;
            }}
            .stSidebar, section[data-testid="stSidebar"] {{
                background: linear-gradient(135deg, rgba(37,99,235,0.08), rgba(249,250,251,1));
            }}
            .stButton>button {{
                background-color: var(--primary);
                color: white;
                border: 0;
                border-radius: 8px;
            }}
            .stButton>button:hover {{
                background-color: #1d4ed8;
            }}
            .stMetric label, .stMetric span {{
                color: #111827 !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def toast_info(msg: str) -> None:
    st.toast(msg, icon="ℹ️")


def toast_success(msg: str) -> None:
    st.toast(msg, icon="✅")


def toast_warning(msg: str) -> None:
    st.toast(msg, icon="⚠️")


def log(message: str) -> None:
    """Basic logging to Streamlit status area."""
    st.sidebar.caption(f"Log: {message}")


def notify_placeholder(title: str, body: Optional[str] = None) -> None:
    """Placeholder for notifications; uses toast for now."""
    if body:
        st.toast(f"{title}: {body}", icon="🔔")
    else:
        st.toast(title, icon="🔔")


def format_ts(ts: str) -> str:
    """Format ISO timestamp to a friendly string."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts
