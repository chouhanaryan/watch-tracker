from app.watchers import shopify


def norm(pid, title, available=True, price="1000.00", handle=None):
    return {
        "external_id": str(pid),
        "handle": handle or title.lower().replace(" ", "-"),
        "title": title,
        "url": f"https://shop.example/products/{handle or title.lower().replace(' ', '-')}",
        "price": price,
        "currency": None,
        "available": available,
        "image_url": None,
    }


def stored(pid, title, available=True, price="1000.00", removed=0):
    p = norm(pid, title, available, price)
    p["removed"] = removed
    return p


def test_new_product_is_a_drop():
    previous = {"1": stored(1, "Chronograph I")}
    current = [norm(1, "Chronograph I"), norm(2, "Calendrier Type 2")]
    events = shopify.diff_products(previous, current)
    assert len(events) == 1
    assert events[0]["kind"] == "new_drop"
    assert "Calendrier Type 2" in events[0]["title"]


def test_restock_and_sold_out():
    previous = {
        "1": stored(1, "Classic Mori", available=False),
        "2": stored(2, "Grand Urushi", available=True),
    }
    current = [
        norm(1, "Classic Mori", available=True),
        norm(2, "Grand Urushi", available=False),
    ]
    kinds = {e["kind"] for e in shopify.diff_products(previous, current)}
    assert kinds == {"restock", "sold_out"}


def test_price_change():
    previous = {"1": stored(1, "Classic Mori", price="1875.00")}
    current = [norm(1, "Classic Mori", price="1950.00")]
    events = shopify.diff_products(previous, current)
    assert len(events) == 1
    assert events[0]["kind"] == "price_change"
    assert "1875.00 -> 1950.00" in events[0]["details"]


def test_removed_product():
    previous = {"1": stored(1, "Classic Mori"), "2": stored(2, "Old Model")}
    current = [norm(1, "Classic Mori")]
    events = shopify.diff_products(previous, current)
    assert len(events) == 1
    assert events[0]["kind"] == "product_removed"


def test_already_removed_product_not_reannounced():
    previous = {"1": stored(1, "Classic Mori"), "2": stored(2, "Old Model", removed=1)}
    current = [norm(1, "Classic Mori")]
    assert shopify.diff_products(previous, current) == []


def test_no_changes_no_events():
    previous = {"1": stored(1, "Classic Mori")}
    current = [norm(1, "Classic Mori")]
    assert shopify.diff_products(previous, current) == []


def test_normalize_aggregates_variants():
    raw = {
        "id": 42,
        "handle": "toki",
        "title": "Toki",
        "variants": [
            {"price": "3800.00", "available": False},
            {"price": "3950.00", "available": True},
        ],
        "images": [{"src": "https://cdn.example/toki.jpg"}],
    }
    p = shopify._normalize("https://kuronotokyo.com", raw)
    assert p["external_id"] == "42"
    assert p["available"] is True
    assert p["price"] == "3800.00 / 3950.00"
    assert p["url"] == "https://kuronotokyo.com/products/toki"
    assert p["image_url"] == "https://cdn.example/toki.jpg"
