"""SQLite persistence layer.

A thin wrapper around sqlite3 — one connection per call, WAL mode, dict rows.
Small enough that an ORM would be more code than it saves.
"""

import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    watcher_type TEXT NOT NULL DEFAULT 'auto',
    check_interval_minutes INTEGER NOT NULL DEFAULT 10,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    last_status TEXT,
    products_baselined INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    handle TEXT,
    title TEXT,
    url TEXT,
    price TEXT,
    currency TEXT,
    available INTEGER,
    ever_available INTEGER NOT NULL DEFAULT 0,
    image_url TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    removed INTEGER NOT NULL DEFAULT 0,
    UNIQUE (site_id, external_id)
);

CREATE TABLE IF NOT EXISTS page_snapshots (
    site_id INTEGER PRIMARY KEY REFERENCES sites(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    text_content TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    url TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    notified INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_site ON events(site_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_detected ON events(detected_at DESC);

CREATE TABLE IF NOT EXISTS discovered_links (
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    handle TEXT NOT NULL,
    url TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (site_id, handle)
);

CREATE TABLE IF NOT EXISTS recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or config.DATABASE_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db(db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Migrations for databases created before these columns existed.
        _ensure_column(conn, "sites", "products_baselined",
                       "products_baselined INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "products", "ever_available",
                       "ever_available INTEGER NOT NULL DEFAULT 0")
        # Backfill: sites that already have stored products were baselined
        # under the old products-exist heuristic; anything ever seen in
        # stock has, by definition, been available.
        conn.execute(
            "UPDATE sites SET products_baselined = 1 "
            "WHERE products_baselined = 0 "
            "AND id IN (SELECT DISTINCT site_id FROM products)"
        )
        conn.execute("UPDATE products SET ever_available = 1 WHERE available = 1")


# --- sites ---

def list_sites(conn):
    return conn.execute("SELECT * FROM sites ORDER BY name").fetchall()


def get_site(conn, site_id: int):
    return conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()


def add_site(conn, name: str, url: str, watcher_type: str = "auto",
             check_interval_minutes: int | None = None) -> int:
    interval = check_interval_minutes or config.DEFAULT_CHECK_INTERVAL_MINUTES
    cur = conn.execute(
        "INSERT INTO sites (name, url, watcher_type, check_interval_minutes) VALUES (?, ?, ?, ?)",
        (name, url, watcher_type, interval),
    )
    return cur.lastrowid


def update_site_status(conn, site_id: int, status: str) -> None:
    conn.execute(
        "UPDATE sites SET last_checked_at = datetime('now'), last_status = ? WHERE id = ?",
        (status, site_id),
    )


def set_site_watcher_type(conn, site_id: int, watcher_type: str) -> None:
    conn.execute("UPDATE sites SET watcher_type = ? WHERE id = ?", (watcher_type, site_id))


def set_products_baselined(conn, site_id: int) -> None:
    conn.execute("UPDATE sites SET products_baselined = 1 WHERE id = ?", (site_id,))


def set_site_enabled(conn, site_id: int, enabled: bool) -> None:
    conn.execute("UPDATE sites SET enabled = ? WHERE id = ?", (1 if enabled else 0, site_id))


def delete_site(conn, site_id: int) -> None:
    conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))


def due_sites(conn):
    """Enabled sites whose interval has elapsed since their last check."""
    return conn.execute(
        """
        SELECT * FROM sites
        WHERE enabled = 1
          AND (last_checked_at IS NULL
               OR datetime(last_checked_at, '+' || check_interval_minutes || ' minutes')
                  <= datetime('now'))
        """
    ).fetchall()


# --- products ---

def products_for_site(conn, site_id: int, include_removed: bool = False):
    q = "SELECT * FROM products WHERE site_id = ?"
    if not include_removed:
        q += " AND removed = 0"
    return conn.execute(q + " ORDER BY first_seen_at DESC", (site_id,)).fetchall()


def upsert_product(conn, site_id: int, p: dict) -> None:
    conn.execute(
        """
        INSERT INTO products (site_id, external_id, handle, title, url, price, currency,
                              available, ever_available, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (site_id, external_id) DO UPDATE SET
            handle = excluded.handle,
            title = excluded.title,
            url = excluded.url,
            price = excluded.price,
            currency = excluded.currency,
            available = excluded.available,
            ever_available = CASE WHEN excluded.available = 1 THEN 1
                                  ELSE products.ever_available END,
            image_url = excluded.image_url,
            last_seen_at = datetime('now'),
            removed = 0
        """,
        (site_id, p["external_id"], p.get("handle"), p.get("title"), p.get("url"),
         p.get("price"), p.get("currency"), 1 if p.get("available") else 0,
         1 if p.get("available") else 0, p.get("image_url")),
    )


def mark_product_removed(conn, site_id: int, external_id: str) -> None:
    conn.execute(
        "UPDATE products SET removed = 1, last_seen_at = datetime('now') "
        "WHERE site_id = ? AND external_id = ?",
        (site_id, external_id),
    )


# --- snapshots ---

def get_snapshot(conn, site_id: int):
    return conn.execute(
        "SELECT * FROM page_snapshots WHERE site_id = ?", (site_id,)
    ).fetchone()


def save_snapshot(conn, site_id: int, content_hash: str, text_content: str) -> None:
    conn.execute(
        """
        INSERT INTO page_snapshots (site_id, content_hash, text_content, fetched_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT (site_id) DO UPDATE SET
            content_hash = excluded.content_hash,
            text_content = excluded.text_content,
            fetched_at = datetime('now')
        """,
        (site_id, content_hash, text_content),
    )


# --- events ---

def add_event(conn, site_id: int, kind: str, title: str, details: str = "",
              url: str = "", notified: bool = False) -> int:
    cur = conn.execute(
        "INSERT INTO events (site_id, kind, title, details, url, notified) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (site_id, kind, title, details, url, 1 if notified else 0),
    )
    return cur.lastrowid


def recent_events(conn, limit: int = 50, site_id: int | None = None):
    if site_id is not None:
        return conn.execute(
            """
            SELECT events.*, sites.name AS site_name FROM events
            JOIN sites ON sites.id = events.site_id
            WHERE site_id = ? ORDER BY events.id DESC LIMIT ?
            """,
            (site_id, limit),
        ).fetchall()
    return conn.execute(
        """
        SELECT events.*, sites.name AS site_name FROM events
        JOIN sites ON sites.id = events.site_id
        ORDER BY events.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()


def mark_events_notified(conn, event_ids: list[int]) -> None:
    conn.executemany("UPDATE events SET notified = 1 WHERE id = ?",
                     [(i,) for i in event_ids])


# --- discovered links (unlisted-product safety net) ---

def known_link_handles(conn, site_id: int) -> set:
    rows = conn.execute(
        "SELECT handle FROM discovered_links WHERE site_id = ?", (site_id,)
    ).fetchall()
    return {r["handle"] for r in rows}


def add_discovered_link(conn, site_id: int, handle: str, url: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO discovered_links (site_id, handle, url) VALUES (?, ?, ?)",
        (site_id, handle, url),
    )


# --- recipients ---

def list_recipients(conn):
    return conn.execute("SELECT * FROM recipients ORDER BY email").fetchall()


def add_recipient(conn, email: str) -> None:
    conn.execute("INSERT OR IGNORE INTO recipients (email) VALUES (?)", (email,))


def delete_recipient(conn, recipient_id: int) -> None:
    conn.execute("DELETE FROM recipients WHERE id = ?", (recipient_id,))
