"""Coverage for the unlisted-drop safety net: Shopify lets a merchant mark a
product 'unlisted' — live at a direct URL, purchasable, but excluded from
products.json / sitemap / search. A brand can only get customers to such a
product by linking it from somewhere on the site, so scanning the homepage
HTML for /products/<handle> links we don't already know about catches it."""

import httpx

from app import checker, db
from app.watchers import html_watcher
from tests.test_checker import FakeStore, add_test_site, shopify_product


def test_extract_product_links_from_anchors():
    html = """
    <html><body>
      <a href="/products/secret-drop">Shop the drop</a>
      <a href="https://kuronotokyo.com/products/toki?variant=123">Toki</a>
      <a href="/collections/all/products/nested-handle#reviews">Nested</a>
      <a href="/cart">Cart</a>
      <script>var url = "/products/should-not-match-script";</script>
    </body></html>
    """
    links = html_watcher.extract_product_links(html, "https://kuronotokyo.com")
    assert links == {
        "secret-drop": "https://kuronotokyo.com/products/secret-drop",
        "toki": "https://kuronotokyo.com/products/toki",
        "nested-handle": "https://kuronotokyo.com/collections/all/products/nested-handle",
    }


def test_link_to_unlisted_product_fires_event(conn):
    store = FakeStore([shopify_product(1, "Toki")])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())  # baseline

    store.homepage = '<html><body><a href="/products/secret-drop">New drop</a></body></html>'
    site = db.get_site(conn, site["id"])
    events = checker.check_site(conn, site, client=store.client())

    kinds = [e["kind"] for e in events]
    assert "unlisted_link" in kinds
    ev = next(e for e in events if e["kind"] == "unlisted_link")
    assert ev["url"] == "https://kuronotokyo.com/products/secret-drop"
    assert "Secret Drop" in ev["title"]


def test_unlisted_link_not_reannounced_on_next_check(conn):
    store = FakeStore([shopify_product(1, "Toki")])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())

    store.homepage = '<html><body><a href="/products/secret-drop">New drop</a></body></html>'
    site = db.get_site(conn, site["id"])
    checker.check_site(conn, site, client=store.client())  # fires once

    site = db.get_site(conn, site["id"])
    events = checker.check_site(conn, site, client=store.client())  # same homepage again
    assert not any(e["kind"] == "unlisted_link" for e in events)


def test_link_to_already_catalogued_product_is_not_flagged(conn):
    store = FakeStore([shopify_product(1, "Toki")])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())

    store.homepage = '<html><body><a href="/products/toki">Toki</a></body></html>'
    site = db.get_site(conn, site["id"])
    events = checker.check_site(conn, site, client=store.client())
    assert not any(e["kind"] == "unlisted_link" for e in events)


def test_unlisted_link_later_appearing_in_catalog_fires_new_drop_not_link(conn):
    store = FakeStore([shopify_product(1, "Toki")])
    site = add_test_site(conn)
    checker.check_site(conn, site, client=store.client())

    store.homepage = '<html><body><a href="/products/secret-drop">New drop</a></body></html>'
    site = db.get_site(conn, site["id"])
    events = checker.check_site(conn, site, client=store.client())
    assert [e["kind"] for e in events if e["kind"] != "page_change"] == ["unlisted_link"]

    # brand publishes it properly into the catalog (title -> handle "secret-drop")
    store.products.append(shopify_product(2, "Secret Drop"))
    site = db.get_site(conn, site["id"])
    events = checker.check_site(conn, site, client=store.client())
    assert [e["kind"] for e in events if e["kind"] != "page_change"] == ["new_drop"]


def test_html_only_site_skips_link_scan(conn):
    """No catalog to compare against for non-Shopify sites, so this only
    makes sense for Shopify-detected sites."""
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products.json":
            return httpx.Response(404)
        return httpx.Response(200, text='<html><body><a href="/products/x">X</a></body></html>')
    transport = httpx.MockTransport(handle)
    site = add_test_site(conn, url="https://indie.example")
    events = checker.check_site(conn, site, client=httpx.Client(transport=transport))
    assert events == []
