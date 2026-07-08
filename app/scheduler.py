"""Background scheduler: every minute, check any site whose interval is due."""

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from . import checker, db

log = logging.getLogger(__name__)

_lock = threading.Lock()


def run_due_checks() -> None:
    if not _lock.acquire(blocking=False):
        return  # previous sweep still running; skip this tick
    try:
        conn = db.connect()
        try:
            for site in db.due_sites(conn):
                events = checker.check_site(conn, site)
                if events:
                    log.info("%s: %d new event(s)", site["name"], len(events))
        finally:
            conn.close()
    finally:
        _lock.release()


def start() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_due_checks, "interval", seconds=60, id="due-checks",
                      max_instances=1, coalesce=True)
    scheduler.start()
    log.info("Scheduler started (sweeps for due sites every 60s)")
    return scheduler
