"""Shopify catalog watcher.

Shopify storefronts expose their catalog at /products.json. Diffing that
against what we've seen before gives precise events: a product we've never
seen is a new drop; sold-out -> available is a restock; price moves are
price changes. Far more reliable than diffing rendered HTML.
"""

import json

import httpx

PAGE_SIZE = 250
MAX_PAGES = 20  # safety cap: 5000 products is plenty for boutique brands


def products_url(base_url: str, page: int = 1) -> str:
    return f"{base_url.rstrip('/')}/products.json?limit={PAGE_SIZE}&page={page}"


def is_shopify(client: httpx.Client, base_url: str) -> bool:
    """True if the site serves a Shopify-style products.json catalog."""
    try:
        resp = client.get(products_url(base_url))
        if resp.status_code != 200:
            return False
        data = resp.json()
        return isinstance(data, dict) and isinstance(data.get("products"), list)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return False


def fetch_products(client: httpx.Client, base_url: str) -> list[dict]:
    """Fetch the full catalog, normalized to the fields we track."""
    out = []
    for page in range(1, MAX_PAGES + 1):
        resp = client.get(products_url(base_url, page))
        resp.raise_for_status()
        products = resp.json().get("products", [])
        if not products:
            break
        for p in products:
            out.append(_normalize(base_url, p))
        if len(products) < PAGE_SIZE:
            break
    return out


def _normalize(base_url: str, p: dict) -> dict:
    variants = p.get("variants") or []
    prices = sorted({v.get("price") for v in variants if v.get("price")})
    available = any(v.get("available") for v in variants)
    images = p.get("images") or []
    return {
        "external_id": str(p.get("id")),
        "handle": p.get("handle") or "",
        "title": p.get("title") or "(untitled)",
        "url": f"{base_url.rstrip('/')}/products/{p.get('handle')}" if p.get("handle") else base_url,
        "price": " / ".join(prices) if prices else None,
        "currency": None,  # products.json doesn't carry currency; price strings are shop-local
        "available": available,
        "image_url": images[0].get("src") if images else None,
    }


def diff_products(previous: dict[str, dict], current: list[dict]) -> list[dict]:
    """Compare stored products (keyed by external_id) with a fresh fetch.

    Returns event dicts: {kind, title, details, url}.
    """
    events = []
    seen_ids = set()
    for p in current:
        seen_ids.add(p["external_id"])
        old = previous.get(p["external_id"])
        if old is None:
            events.append({
                "kind": "new_drop",
                "title": f"New product: {p['title']}",
                "details": _drop_details(p),
                "url": p["url"],
            })
            continue
        if not old["available"] and p["available"]:
            events.append({
                "kind": "restock",
                "title": f"Back in stock: {p['title']}",
                "details": f"Price: {p['price'] or 'n/a'}",
                "url": p["url"],
            })
        elif old["available"] and not p["available"]:
            events.append({
                "kind": "sold_out",
                "title": f"Sold out: {p['title']}",
                "details": "",
                "url": p["url"],
            })
        if old.get("price") and p.get("price") and old["price"] != p["price"]:
            events.append({
                "kind": "price_change",
                "title": f"Price change: {p['title']}",
                "details": f"{old['price']} -> {p['price']}",
                "url": p["url"],
            })
        if old.get("title") and old["title"] != p["title"]:
            events.append({
                "kind": "product_change",
                "title": f"Product renamed: {old['title']} -> {p['title']}",
                "details": "",
                "url": p["url"],
            })
    for external_id, old in previous.items():
        if external_id not in seen_ids and not old.get("removed"):
            events.append({
                "kind": "product_removed",
                "title": f"Removed from store: {old['title']}",
                "details": "",
                "url": old.get("url") or "",
            })
    return events


def _drop_details(p: dict) -> str:
    bits = []
    if p.get("price"):
        bits.append(f"Price: {p['price']}")
    bits.append("In stock" if p.get("available") else "Not yet purchasable (listed)")
    return " | ".join(bits)
