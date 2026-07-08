"""End-to-end checker tests against a fake Shopify store served by
httpx.MockTransport — no network involved."""

import json

import httpx

from app import checker, db


def shopify_product(pid, title, available=True, price="3800.00"):
    return {
        "id": pid,
        "handle": title.lower().replace(" ", "-"),
        "title": title,
        "variants": [{"price": price, "available": available}],
        "images": [],
    }


class FakeStore:
    """Mutable fake Shopify site: catalog + homepage HTML."""

    def __init__(self, products, homepage="<html><body>Kurono Tokyo</body></html>"):
        self.products = products
        self.homepage = homepage
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products.json":
            page = int(request.url.params.get("page", "1"))
            items = self.products if page == 1 else []
            return httpx.Response(200, json={"products": items})
        return httpx.Response(200, text=self.homepage)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport)


def add_test_site(conn, url="https://kuronotokyo.com"):
    site_id = db.add_site(conn, "Kurono Tokyo", url)
    conn.commit()
    return db.get_site(conn, site_id)


def test_first_check_is_baseline_no_events(conn):
    store = FakeStore([shopify_product(1, "Chronograph I")])
    site = add_test_site(conn)
    events = checker.check_site(conn, site, client=store.client())
    assert events == []
    site = db.get_site(conn, site["id"])
    assert site["watcher_type"] == "shopify"
    assert site["last_status"] == "ok"
    assert len(db.products_for_site(conn, site["id"])) == 1


def test_new_drop_detected_and_recorded(conn):
    store = FakeStore([shopify_product(1, "Chronograph I")])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())

    store.products.append(shopify_product(2, "Calendrier Type 2", available=False))
    store.homepage = "<html><body>Kurono Tokyo — Calendrier Type 2 coming</body></html>"
    site = db.get_site(conn, site["id"])
    events = checker.check_site(conn, site, client=store.client())

    kinds = {e["kind"] for e in events}
    assert "new_drop" in kinds
    assert "page_change" in kinds  # homepage text changed too
    rows = db.recent_events(conn, site_id=site["id"])
    assert {r["kind"] for r in rows} == kinds
    drop = next(r for r in rows if r["kind"] == "new_drop")
    assert "Calendrier Type 2" in drop["title"]
    assert drop["url"].endswith("/products/calendrier-type-2")


def test_no_change_no_events(conn):
    store = FakeStore([shopify_product(1, "Chronograph I")])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())
    site = db.get_site(conn, site["id"])
    assert checker.check_site(conn, site, client=store.client()) == []


def test_restock_detected(conn):
    store = FakeStore([shopify_product(1, "Toki", available=False)])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())

    store.products = [shopify_product(1, "Toki", available=True)]
    site = db.get_site(conn, site["id"])
    events = checker.check_site(conn, site, client=store.client())
    assert [e["kind"] for e in events] == ["restock"]


def test_non_shopify_site_falls_back_to_html_watch(conn):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products.json":
            return httpx.Response(404)
        return httpx.Response(200, text=handle.page)
    handle.page = "<html><body><p>Independent watchmaker</p></body></html>"
    transport = httpx.MockTransport(handle)

    site = add_test_site(conn, url="https://indie.example")
    events = checker.check_site(conn, site, client=httpx.Client(transport=transport))
    assert events == []
    site = db.get_site(conn, site["id"])
    assert site["watcher_type"] == "html"

    handle.page = "<html><body><p>Independent watchmaker</p><p>New model announced!</p></body></html>"
    events = checker.check_site(conn, site, client=httpx.Client(transport=transport))
    assert [e["kind"] for e in events] == ["page_change"]
    assert "New model announced!" in events[0]["details"]


def test_fetch_error_recorded_not_raised(conn):
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    site = add_test_site(conn, url="https://down.example")
    events = checker.check_site(conn, site, client=httpx.Client(transport=transport))
    assert events == []
    site = db.get_site(conn, site["id"])
    assert site["last_status"].startswith("error:")


def test_notification_marks_events(conn, monkeypatch):
    sent = {}

    def fake_send(site_name, events, recipients):
        sent["site"] = site_name
        sent["events"] = events
        sent["recipients"] = recipients

    from app import checker as checker_mod
    monkeypatch.setattr(checker_mod.notifier, "send_event_email", fake_send)
    monkeypatch.setattr(checker_mod.config, "smtp_configured", lambda: True)

    db.add_recipient(conn, "aryan@example.com")
    conn.commit()

    store = FakeStore([shopify_product(1, "Chronograph I")])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())

    store.products.append(shopify_product(2, "Seiji"))
    site = db.get_site(conn, site["id"])
    checker.check_site(conn, site, client=store.client())

    assert sent["site"] == "Kurono Tokyo"
    assert sent["recipients"] == ["aryan@example.com"]
    assert any(e["kind"] == "new_drop" for e in sent["events"])
    rows = db.recent_events(conn, site_id=site["id"])
    assert all(r["notified"] for r in rows)
