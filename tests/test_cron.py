import json

from app import cron, db
from tests.test_checker import FakeStore, shopify_product


def test_sync_sites_adds_new_and_skips_known(conn, tmp_path):
    sites_file = tmp_path / "sites.json"
    sites_file.write_text(json.dumps([
        {"name": "Kurono Tokyo", "url": "https://kuronotokyo.com/"},
        {"name": "Other Brand", "url": "https://other.example"},
    ]))
    cron.sync_sites(conn, sites_file)
    assert {s["name"] for s in db.list_sites(conn)} == {"Kurono Tokyo", "Other Brand"}

    # idempotent: trailing-slash variants don't duplicate
    cron.sync_sites(conn, sites_file)
    assert len(db.list_sites(conn)) == 2


def test_render_static_writes_dashboard_and_site_pages(conn, tmp_path):
    site_id = db.add_site(conn, "Kurono Tokyo", "https://kuronotokyo.com")
    db.upsert_product(conn, site_id, {
        "external_id": "1", "handle": "toki", "title": "Toki",
        "url": "https://kuronotokyo.com/products/toki",
        "price": "3800.00", "currency": None, "available": True, "image_url": None,
    })
    db.upsert_product(conn, site_id, {
        "external_id": "2", "handle": "seiji", "title": "Seiji",
        "url": "https://kuronotokyo.com/products/seiji",
        "price": "4200.00", "currency": None, "available": False, "image_url": None,
    })
    db.add_event(conn, site_id, "new_drop", "New product: Toki",
                 "Price: 3800.00 | In stock", "https://kuronotokyo.com/products/toki")
    conn.commit()

    out = tmp_path / "public"
    cron.render_static(conn, out)

    index = (out / "index.html").read_text()
    assert "New product: Toki" in index
    assert "New drop" in index
    assert f'href="site-{site_id}.html"' in index
    assert "1 available" in index
    assert "1 coming soon" in index  # never seen in stock -> upcoming

    page = (out / f"site-{site_id}.html").read_text()
    assert "Toki" in page and "Seiji" in page
    assert "Available now" in page
    assert "Coming soon" in page
    assert (out / "static" / "style.css").exists()


def test_render_static_empty_catalog_explains_itself(conn, tmp_path):
    site_id = db.add_site(conn, "Kurono Tokyo", "https://kuronotokyo.com")
    db.set_site_watcher_type(conn, site_id, "shopify")
    conn.commit()

    out = tmp_path / "public"
    cron.render_static(conn, out)

    assert "no products listed right now" in (out / "index.html").read_text()
    assert "unlist their catalog between releases" in (out / f"site-{site_id}.html").read_text()


def test_run_checks_checks_all_enabled_sites(conn, monkeypatch):
    a = db.add_site(conn, "A", "https://a.example")
    b = db.add_site(conn, "B", "https://b.example")
    db.set_site_enabled(conn, b, False)
    conn.commit()

    store = FakeStore([shopify_product(1, "Toki")])
    monkeypatch.setattr(cron.checker, "make_client", store.client)

    cron.run_checks(conn)
    assert db.get_site(conn, a)["last_checked_at"] is not None
    assert db.get_site(conn, b)["last_checked_at"] is None
