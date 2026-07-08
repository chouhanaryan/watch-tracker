"""Generic page watcher: hash the visible text of a page and diff it.

Works for any site. Scripts, styles, and markup are stripped so that
rotating asset hashes, CSRF tokens, and the like don't cause false alarms —
only human-visible text changes count.
"""

import difflib
import hashlib
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

MAX_DIFF_LINES = 40


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "iframe", "svg"]):
        tag.decompose()
    lines = []
    for raw in soup.get_text("\n").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_product_links(html: str, base_url: str) -> dict[str, str]:
    """Map product handle -> canonical URL for every /products/<handle> link
    on the page. Restricted to real <a href> anchors (not raw text/scripts)
    so embedded JSON blobs and trackers don't produce false positives.

    Only sees what's in the static HTML response — links injected by
    client-side JS after page load won't appear here.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/products/" not in href:
            continue
        absolute = urljoin(base_url, href)
        path = urlparse(absolute).path
        idx = path.find("/products/")
        handle = path[idx + len("/products/"):].split("/")[0].strip()
        if handle and handle not in links:
            links[handle] = absolute.split("?")[0].split("#")[0]
    return links


def summarize_diff(old_text: str, new_text: str) -> str:
    """Human-readable added/removed lines, capped to keep events readable."""
    diff = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), lineterm="", n=0
    )
    changes = []
    for line in diff:
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            changes.append(f"Added: {line[1:].strip()}")
        elif line.startswith("-"):
            changes.append(f"Removed: {line[1:].strip()}")
    if not changes:
        return "Page content changed."
    if len(changes) > MAX_DIFF_LINES:
        omitted = len(changes) - MAX_DIFF_LINES
        changes = changes[:MAX_DIFF_LINES] + [f"... and {omitted} more change(s)"]
    return "\n".join(changes)
