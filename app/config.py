import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    """Env var lookup that treats empty strings as unset — GitHub Actions
    passes undefined secrets as "" rather than leaving the variable out."""
    return os.environ.get(name) or default


DATABASE_PATH = _env("DATABASE_PATH", str(BASE_DIR / "data" / "watchtracker.db"))

SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
EMAIL_FROM = _env("EMAIL_FROM") or SMTP_USER
EMAIL_TO = [e.strip() for e in _env("EMAIL_TO").split(",") if e.strip()]

DEFAULT_CHECK_INTERVAL_MINUTES = int(_env("DEFAULT_CHECK_INTERVAL_MINUTES", "10"))
SCHEDULER_ENABLED = _env("SCHEDULER_ENABLED", "1") not in ("0", "false", "False")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 30


def smtp_configured() -> bool:
    return bool(SMTP_HOST and EMAIL_FROM)
