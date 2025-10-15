import streamlit as st
from datetime import datetime
from typing import Optional

# Attempt to use plyer for native notifications; gracefully fall back to Streamlit toasts
try:
    from plyer import notification as plyer_notification  # type: ignore
except Exception:  # pragma: no cover - environment dependent
    plyer_notification = None  # type: ignore


def ocean_styles(primary: str = "#2563EB", secondary: str = "#F59E0B") -> None:
    """Inject basic Ocean Professional theme touches and accessibility helpers."""
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
                outline: none;
            }}
            .stButton>button:hover {{
                background-color: #1d4ed8;
            }}
            .stButton>button:focus-visible {{
                box-shadow: 0 0 0 3px rgba(37,99,235,0.35);
            }}
            .stMetric label, .stMetric span {{
                color: #111827 !important;
            }}
            /* Improve keyboard focus styles for inputs */
            .stTextInput input:focus, .stNumberInput input:focus, .stSelectbox [data-baseweb="select"]:focus {{
                box-shadow: 0 0 0 3px rgba(37,99,235,0.25) !important;
                outline: none !important;
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


# PUBLIC_INTERFACE
def notify_placeholder(title: str, body: Optional[str] = None) -> None:
    """Try native OS notification via plyer, fallback to Streamlit toast."""
    text = f"{title}: {body}" if body else title
    try:
        if plyer_notification is not None:
            plyer_notification.notify(title=title, message=(body or ""), timeout=5)  # non-blocking
            # Also show a small toast for in-app feedback
            st.toast(text, icon="🔔")
        else:
            st.toast(text, icon="🔔")
    except Exception:
        # Any failure falls back to toast
        st.toast(text, icon="🔔")


# PUBLIC_INTERFACE
def confirm_action(key: str, prompt: str) -> bool:
    """Render a small inline confirmation expander with Yes/No buttons."""
    with st.expander(prompt, expanded=True):
        c1, c2 = st.columns([1, 1])
        confirmed = False
        with c1:
            if st.button("Yes, proceed", key=f"{key}_yes"):
                confirmed = True
        with c2:
            st.button("No, cancel", key=f"{key}_no")
    return confirmed


def format_ts(ts: str) -> str:
    """Format ISO timestamp to a friendly string."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts
