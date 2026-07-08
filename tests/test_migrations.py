"""init_db must upgrade databases created before the baseline/status columns
existed — the GitHub Actions deployment carries its DB forward in git."""

import sqlite3

from app import db

OLD_SCHEMA = """
CREATE TABLE sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    watcher_type TEXT NOT NULL DEFAULT 'auto',
    check_interval_minutes INTEGER NOT NULL DEFAULT 10,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    last_status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    external_id TEXT NOT NULL,
    handle TEXT, title TEXT, url TEXT, price TEXT, currency TEXT,
    available INTEGER, image_url TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    removed INTEGER NOT NULL DEFAULT 0,
    UNIQUE (site_id, external_id)
);
"""


def test_migration_adds_columns_and_backfills(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(OLD_SCHEMA)
    old.execute("INSERT INTO sites (name, url) VALUES ('With products', 'https://a.example')")
    old.execute("INSERT INTO sites (name, url) VALUES ('Empty catalog', 'https://b.example')")
    old.execute(
        "INSERT INTO products (site_id, external_id, title, available) VALUES (1, 'x', 'T', 1)"
    )
    old.commit()
    old.close()

    db.init_db(path)

    conn = db.connect(path)
    try:
        sites = {s["name"]: s for s in db.list_sites(conn)}
        # site with stored products was already baselined under the old heuristic
        assert sites["With products"]["products_baselined"] == 1
        # empty-catalog site must NOT be marked baselined
        assert sites["Empty catalog"]["products_baselined"] == 0
        p = db.products_for_site(conn, 1)[0]
        assert p["ever_available"] == 1
    finally:
        conn.close()


def test_init_db_idempotent(tmp_path):
    path = str(tmp_path / "new.db")
    db.init_db(path)
    db.init_db(path)  # must not raise on already-migrated schema
