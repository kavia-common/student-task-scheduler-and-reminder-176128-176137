import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    """Application settings with env var fallback."""
    DATA_DIR: str = "./data"
    NOTIFICATIONS_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60

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

    _settings_singleton = Settings(
        DATA_DIR=data_dir,
        NOTIFICATIONS_ENABLED=notif,
        SCHEDULER_INTERVAL_SECONDS=interval,
    )
    return _settings_singleton
