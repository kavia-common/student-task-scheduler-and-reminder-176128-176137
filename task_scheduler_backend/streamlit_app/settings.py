import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    """Application settings with env var fallback."""
    DATA_DIR: str = "./data"
    NOTIFICATIONS_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60

    # Suggestion engine weights (configurable)
    SUGGESTION_WEIGHT_PRIORITY: float = 1.0
    SUGGESTION_WEIGHT_URGENCY: float = 1.0
    SUGGESTION_WEIGHT_OVERDUE_BOOST: float = 1.0
    SUGGESTION_WEIGHT_SHORT_TASK_BIAS: float = 0.5
    SUGGESTION_SHORT_TASK_THRESHOLD_MIN: int = 30
    SUGGESTION_URGENCY_WINDOW_HOURS: int = 72

    # Theme colors (for potential future use beyond utils.ocean_styles)
    THEME_PRIMARY: str = "#2563EB"
    THEME_SECONDARY: str = "#F59E0B"
    THEME_BACKGROUND: str = "#f9fafb"
    THEME_SURFACE: str = "#ffffff"
    THEME_TEXT: str = "#111827"


_settings_singleton: Optional[Settings] = None


# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """Return a singleton Settings instance loaded from environment variables."""
    global _settings_singleton
    if _settings_singleton is not None:
        return _settings_singleton

    data_dir = os.getenv("DATA_DIR", "./data")
    notif = os.getenv("NOTIFICATIONS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    try:
        interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
    except ValueError:
        interval = 60

    def _get_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)))
        except Exception:
            return default

    def _get_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except Exception:
            return default

    _settings_singleton = Settings(
        DATA_DIR=data_dir,
        NOTIFICATIONS_ENABLED=notif,
        SCHEDULER_INTERVAL_SECONDS=interval,
        SUGGESTION_WEIGHT_PRIORITY=_get_float("SUGGESTION_WEIGHT_PRIORITY", 1.0),
        SUGGESTION_WEIGHT_URGENCY=_get_float("SUGGESTION_WEIGHT_URGENCY", 1.0),
        SUGGESTION_WEIGHT_OVERDUE_BOOST=_get_float("SUGGESTION_WEIGHT_OVERDUE_BOOST", 1.0),
        SUGGESTION_WEIGHT_SHORT_TASK_BIAS=_get_float("SUGGESTION_WEIGHT_SHORT_TASK_BIAS", 0.5),
        SUGGESTION_SHORT_TASK_THRESHOLD_MIN=_get_int("SUGGESTION_SHORT_TASK_THRESHOLD_MIN", 30),
        SUGGESTION_URGENCY_WINDOW_HOURS=_get_int("SUGGESTION_URGENCY_WINDOW_HOURS", 72),
    )
    return _settings_singleton
