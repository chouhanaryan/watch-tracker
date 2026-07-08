import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import checker, config, db, scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("watchtracker")

SEED_SITES = [
    {"name": "Kurono Tokyo", "url": "https://kuronotokyo.com"},
]

_scheduler = None


def seed(conn) -> None:
    if not db.list_sites(conn):
        for s in SEED_SITES:
            db.add_site(conn, s["name"], s["url"])
            log.info("Seeded site: %s", s["name"])
    if not db.list_recipients(conn):
        for email in config.EMAIL_TO:
            db.add_recipient(conn, email)
            log.info("Seeded recipient: %s", email)
    conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    db.init_db()
    conn = db.connect()
    try:
        seed(conn)
    finally:
        conn.close()
    if config.SCHEDULER_ENABLED:
        _scheduler = scheduler.start()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="Watch Tracker", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

KIND_META = {
    "new_drop": {"label": "New drop", "css": "drop"},
    "restock": {"label": "Restock", "css": "restock"},
    "sold_out": {"label": "Sold out", "css": "soldout"},
    "price_change": {"label": "Price change", "css": "price"},
    "product_change": {"label": "Product updated", "css": "change"},
    "product_removed": {"label": "Removed", "css": "removed"},
    "page_change": {"label": "Page updated", "css": "page"},
}
templates.env.globals["kind_meta"] = lambda kind: KIND_META.get(
    kind, {"label": kind, "css": "change"}
)
templates.env.globals["smtp_configured"] = config.smtp_configured


def _validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    return url.rstrip("/")


@app.get("/")
def dashboard(request: Request):
    conn = db.connect()
    try:
        sites = db.list_sites(conn)
        events = db.recent_events(conn, limit=50)
        recipients = db.list_recipients(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "dashboard.html", {
        "sites": sites, "events": events, "recipients": recipients,
    })


@app.get("/sites/{site_id}")
def site_detail(request: Request, site_id: int):
    conn = db.connect()
    try:
        site = db.get_site(conn, site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")
        events = db.recent_events(conn, limit=100, site_id=site_id)
        products = db.products_for_site(conn, site_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "site_detail.html", {
        "site": site, "events": events, "products": products,
    })


@app.post("/sites")
def create_site(name: str = Form(...), url: str = Form(...),
                interval: int = Form(config.DEFAULT_CHECK_INTERVAL_MINUTES)):
    url = _validate_url(url)
    interval = max(1, interval)
    conn = db.connect()
    try:
        try:
            db.add_site(conn, name.strip() or url, url, check_interval_minutes=interval)
            conn.commit()
        except db.sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="That URL is already tracked")
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@app.post("/sites/{site_id}/check")
def check_now(site_id: int):
    conn = db.connect()
    try:
        site = db.get_site(conn, site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")
        checker.check_site(conn, site)
    finally:
        conn.close()
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


@app.post("/sites/{site_id}/toggle")
def toggle_site(site_id: int):
    conn = db.connect()
    try:
        site = db.get_site(conn, site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")
        db.set_site_enabled(conn, site_id, not site["enabled"])
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@app.post("/sites/{site_id}/delete")
def remove_site(site_id: int):
    conn = db.connect()
    try:
        db.delete_site(conn, site_id)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@app.post("/recipients")
def create_recipient(email: str = Form(...)):
    email = email.strip()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    conn = db.connect()
    try:
        db.add_recipient(conn, email)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@app.post("/recipients/{recipient_id}/delete")
def remove_recipient(recipient_id: int):
    conn = db.connect()
    try:
        db.delete_recipient(conn, recipient_id)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


# --- JSON API (for future integrations) ---

@app.get("/api/sites")
def api_sites():
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_sites(conn)]
    finally:
        conn.close()


@app.get("/api/events")
def api_events(limit: int = 50):
    conn = db.connect()
    try:
        return [dict(r) for r in db.recent_events(conn, limit=min(limit, 500))]
    finally:
        conn.close()


@app.get("/healthz")
def healthz():
    return {"ok": True}
