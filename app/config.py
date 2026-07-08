import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "watchtracker.db"))

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "") or SMTP_USER
EMAIL_TO = [e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if e.strip()]

DEFAULT_CHECK_INTERVAL_MINUTES = int(os.environ.get("DEFAULT_CHECK_INTERVAL_MINUTES", "10"))
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") not in ("0", "false", "False")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 30


def smtp_configured() -> bool:
    return bool(SMTP_HOST and EMAIL_FROM)
