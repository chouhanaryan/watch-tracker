"""Product status derivation, shared by the web app and the static builder.

A product that is listed but has never been purchasable is treated as an
upcoming release — that's how drop-based brands like Kurono stage products —
whereas one that used to be purchasable is sold out.
"""


def product_status(p) -> dict:
    if p["available"]:
        return {"code": "in_stock", "label": "Available now", "css": "restock"}
    if p["ever_available"]:
        return {"code": "sold_out", "label": "Sold out", "css": "soldout"}
    return {"code": "upcoming", "label": "Coming soon", "css": "upcoming"}
