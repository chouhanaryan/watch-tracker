"""Runs a single check of a site: fetch, diff, record events, notify."""

import logging

import httpx

from . import config, db, notifier
from .watchers import html_watcher, shopify

log = logging.getLogger(__name__)


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    )


def check_site(conn, site, client: httpx.Client | None = None) -> list[dict]:
    """Check one site. Returns the list of new events (already persisted).

    `site` is a row/dict with id, url, watcher_type. Errors are recorded on
    the site row rather than raised, so one bad site can't stall the loop.
    """
    owns_client = client is None
    if owns_client:
        client = make_client()
    events: list[dict] = []
    try:
        watcher_type = site["watcher_type"]
        if watcher_type == "auto":
            watcher_type = "shopify" if shopify.is_shopify(client, site["url"]) else "html"
            db.set_site_watcher_type(conn, site["id"], watcher_type)
            log.info("Site %s detected as %s", site["url"], watcher_type)

        homepage = client.get(site["url"])
        homepage.raise_for_status()

        if watcher_type == "shopify":
            events += _check_shopify(conn, site, client, homepage.text)
        events += _check_page(conn, site, homepage.text)

        db.update_site_status(conn, site["id"], "ok")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - status surface for any fetch/parse failure
        log.warning("Check failed for %s: %s", site["url"], exc)
        db.update_site_status(conn, site["id"], f"error: {exc}")
        conn.commit()
        return []
    finally:
        if owns_client:
            client.close()

    if events:
        _notify(conn, site, events)
    return events


def _check_shopify(conn, site, client, homepage_html: str) -> list[dict]:
    current = shopify.fetch_products(client, site["url"])
    stored = db.products_for_site(conn, site["id"], include_removed=True)
    previous = {row["external_id"]: dict(row) for row in stored}

    # An explicit flag, not "no products stored yet": brands like Kurono
    # empty their catalog between drops, and treating every empty-catalog
    # check as a fresh baseline would swallow the next drop's events.
    first_run = not site["products_baselined"]
    events = [] if first_run else shopify.diff_products(previous, current)

    for p in current:
        db.upsert_product(conn, site["id"], p)
    current_ids = {p["external_id"] for p in current}
    for external_id in previous:
        if external_id not in current_ids:
            db.mark_product_removed(conn, site["id"], external_id)

    persisted = []
    for ev in events:
        ev["_id"] = db.add_event(conn, site["id"], ev["kind"], ev["title"],
                                 ev["details"], ev["url"])
        persisted.append(ev)
    if first_run:
        db.set_products_baselined(conn, site["id"])
        log.info("Baseline: stored %d products for %s", len(current), site["url"])

    known_handles = {p.get("handle") for p in current if p.get("handle")}
    known_handles |= {row["handle"] for row in stored if row["handle"]}
    persisted += _check_unlisted_links(conn, site, homepage_html, known_handles)
    return persisted


def _check_unlisted_links(conn, site, homepage_html: str, known_handles: set) -> list[dict]:
    """Flag product links on the homepage that aren't in the catalog.

    Shopify lets a merchant mark a product "unlisted": live at a direct URL
    and fully purchasable, but deliberately excluded from products.json, the
    sitemap, and search — the mechanism drop brands use for links shared
    first via social/Discord. Catalog diffing alone can't see those; this
    catches them the moment the brand links one from the page we already
    fetch every check.
    """
    links = html_watcher.extract_product_links(homepage_html, site["url"])
    already_flagged = db.known_link_handles(conn, site["id"])
    known = known_handles | already_flagged

    persisted = []
    for handle, url in links.items():
        if handle in known:
            continue
        db.add_discovered_link(conn, site["id"], handle, url)
        label = handle.replace("-", " ").replace("_", " ").title()
        ev = {
            "kind": "unlisted_link",
            "title": f"New product link found on site: {label}",
            "details": ("Linked on the page but not in the product catalog — "
                        "may be an early or unlisted drop. Worth checking by hand."),
            "url": url,
        }
        ev["_id"] = db.add_event(conn, site["id"], ev["kind"], ev["title"],
                                 ev["details"], ev["url"])
        persisted.append(ev)
    return persisted


def _check_page(conn, site, homepage_html: str) -> list[dict]:
    text = html_watcher.extract_text(homepage_html)
    new_hash = html_watcher.content_hash(text)

    snapshot = db.get_snapshot(conn, site["id"])
    if snapshot is None:
        db.save_snapshot(conn, site["id"], new_hash, text)
        return []
    if snapshot["content_hash"] == new_hash:
        return []

    details = html_watcher.summarize_diff(snapshot["text_content"] or "", text)
    db.save_snapshot(conn, site["id"], new_hash, text)
    ev = {
        "kind": "page_change",
        "title": "Page content changed",
        "details": details,
        "url": site["url"],
    }
    ev["_id"] = db.add_event(conn, site["id"], ev["kind"], ev["title"],
                             ev["details"], ev["url"])
    return [ev]


def _notify(conn, site, events: list[dict]) -> None:
    recipients = [r["email"] for r in db.list_recipients(conn)]
    if not recipients:
        log.info("No recipients configured; skipping email for %s", site["name"])
        return
    if not config.smtp_configured():
        log.info("SMTP not configured; skipping email for %s", site["name"])
        return
    try:
        notifier.send_event_email(site["name"], events, recipients)
        db.mark_events_notified(conn, [ev["_id"] for ev in events if "_id" in ev])
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - email failure must not kill the check loop
        log.error("Failed to send email for %s: %s", site["name"], exc)
