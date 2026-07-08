"""One-shot check run + static dashboard build, for GitHub Actions / cron.

Usage: python -m app.cron --output public

Reads the site list from sites.json (checks every enabled site each run —
the cron schedule controls cadence, not per-site intervals), records events,
sends emails if SMTP is configured, and renders a read-only HTML dashboard
suitable for GitHub Pages.
"""

import argparse
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import checker, config, db

log = logging.getLogger("watchtracker.cron")

APP_DIR = Path(__file__).parent

KIND_META = {
    "new_drop": {"label": "New drop", "css": "drop"},
    "restock": {"label": "Restock", "css": "restock"},
    "sold_out": {"label": "Sold out", "css": "soldout"},
    "price_change": {"label": "Price change", "css": "price"},
    "product_change": {"label": "Product updated", "css": "change"},
    "product_removed": {"label": "Removed", "css": "removed"},
    "page_change": {"label": "Page updated", "css": "page"},
}


def sync_sites(conn, sites_file: Path) -> None:
    """Ensure every site in sites.json exists in the DB (never deletes)."""
    entries = json.loads(sites_file.read_text())
    known = {row["url"].rstrip("/") for row in db.list_sites(conn)}
    for entry in entries:
        url = entry["url"].rstrip("/")
        if url not in known:
            db.add_site(conn, entry.get("name", url), url,
                        entry.get("watcher_type", "auto"))
            log.info("Added site from sites.json: %s", url)
    conn.commit()


def seed_recipients(conn) -> None:
    for email in config.EMAIL_TO:
        db.add_recipient(conn, email)
    conn.commit()


def run_checks(conn) -> int:
    total = 0
    for site in db.list_sites(conn):
        if not site["enabled"]:
            continue
        events = checker.check_site(conn, site)
        if events:
            log.info("%s: %d new event(s)", site["name"], len(events))
        total += len(events)
    return total


def render_static(conn, out_dir: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(APP_DIR / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["kind_meta"] = lambda kind: KIND_META.get(
        kind, {"label": kind, "css": "change"}
    )
    sites = db.list_sites(conn)
    html = env.get_template("static_index.html").render(
        sites=sites,
        events=db.recent_events(conn, limit=100),
        products_by_site={s["id"]: db.products_for_site(conn, s["id"]) for s in sites},
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html)
    static_out = out_dir / "static"
    static_out.mkdir(exist_ok=True)
    shutil.copy(APP_DIR / "static" / "style.css", static_out / "style.css")
    log.info("Static dashboard written to %s", out_dir / "index.html")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", default="sites.json", help="path to sites.json")
    parser.add_argument("--output", default="public",
                        help="directory for the static dashboard")
    parser.add_argument("--skip-checks", action="store_true",
                        help="render the dashboard without checking sites")
    args = parser.parse_args(argv)

    db.init_db()
    conn = db.connect()
    try:
        sync_sites(conn, Path(args.sites))
        seed_recipients(conn)
        if not args.skip_checks:
            new_events = run_checks(conn)
            log.info("Run complete: %d new event(s)", new_events)
        render_static(conn, Path(args.output))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
