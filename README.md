# ⌚ Watch Tracker

Tracks watch-brand websites for updates — most importantly **new drops** — and
alerts you by email. Ships with [Kurono Tokyo](https://kuronotokyo.com) pre-seeded,
and any other brand can be added from the web dashboard.

## How it works

Every site is checked on its own interval (default: every 10 minutes) by one of
two watchers, auto-detected when the site is first checked:

- **Shopify watcher** — most boutique watch brands (Kurono Tokyo included) run on
  Shopify, which exposes the product catalog at `/products.json`. The tracker
  diffs the catalog between checks, giving precise, product-level events:
  - 🚨 **New drop** — a product appears that was never seen before
  - **Restock** — sold out → available
  - **Sold out**, **price change**, **rename**, **removed**

  It *also* watches the homepage text, so non-product updates (a "next drop:
  July 14" banner, a journal post teaser) are caught too.

  **Unlisted-product safety net**: Shopify lets a merchant mark a product
  "unlisted" — live at a direct URL and fully purchasable, but deliberately
  excluded from `products.json`, the sitemap, and search. Drop brands use
  this for links shared first via social/Discord, and catalog diffing alone
  can't see it. Every check also scans the homepage HTML for `/products/<handle>`
  links; any handle that isn't already in the catalog fires a 👀 **Possible
  new listing** event so you can check it by hand. Once a flagged link
  actually appears in the catalog, the normal 🚨 new-drop event takes over
  and the link isn't re-flagged.

- **HTML watcher** (fallback for non-Shopify sites) — extracts the visible text
  of the page (scripts/styles stripped, so rotating tokens don't cause false
  alarms), hashes it, and reports a readable added/removed-lines diff when it
  changes.

The **first check of a site records a baseline and sends nothing** — otherwise
every existing product would be announced as a "drop". Changes after that
generate events, which appear on the dashboard and are emailed to all
configured recipients in a single message per check (drops get a 🚨 subject).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then edit — see Email setup below
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. Kurono Tokyo is already being tracked; add more
brands with the *Add a site* form. Use **Check** on any site to run a check
immediately (handy right after adding a site, to establish its baseline).

## Email setup (Gmail)

1. Turn on 2-Step Verification for your Google account.
2. Create an **App Password**: Google Account → Security → 2-Step Verification → App passwords.
3. In `.env`:

   ```ini
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=you@gmail.com
   SMTP_PASSWORD=<the app password>
   EMAIL_TO=you@gmail.com
   ```

Any SMTP provider works the same way (Fastmail, SES, Mailgun SMTP, …).
Recipients can also be added/removed from the dashboard. If SMTP isn't
configured the app still works — events just stay on the dashboard, and the
header shows a warning.

## Configuration

All via `.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | — | outgoing mail server |
| `EMAIL_FROM` | `SMTP_USER` | From address |
| `EMAIL_TO` | — | comma-separated recipients seeded on first run |
| `DATABASE_PATH` | `data/watchtracker.db` | SQLite location |
| `DEFAULT_CHECK_INTERVAL_MINUTES` | `10` | interval for newly added sites |
| `SCHEDULER_ENABLED` | `1` | set `0` to disable background checks |

## Deploy free with GitHub Actions + GitHub Pages

You don't need a server at all. The included workflow
(`.github/workflows/tracker.yml`) runs the checker **every 30 minutes on
GitHub Actions**, emails alerts, commits tracker state back to the repo
(`state/watchtracker.db`), and publishes a read-only dashboard to
**GitHub Pages** at `https://<user>.github.io/watch-tracker/`.

Setup (once, after merging to `main`):

1. **Settings → Pages → Source: "GitHub Actions"** (the workflow also tries to
   enable this automatically). On a free plan the repo must be public for Pages.
2. **Settings → Secrets and variables → Actions**, add:
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`,
   `EMAIL_TO`. All optional — without them you still get the dashboard, just
   no emails.
3. Run the workflow once by hand (Actions → *Check sites and deploy dashboard*
   → Run workflow) to record the baseline and publish the first dashboard.

In this mode, sites are managed by editing **`sites.json`** and pushing — the
web UI's add/pause/delete forms only exist in server mode. Every listed site
is checked on every workflow run; adjust the `cron:` line to change cadence
(GitHub may delay scheduled runs by a few minutes, and scheduled workflows
only run from the repo's **default branch**).

The same one-shot check also works from any machine's crontab:
`python -m app.cron --output public`.

## Running the full web app permanently

The interactive dashboard (add sites, check now, manage recipients) is a
server process, so it wants to live on something always-on: a Raspberry Pi,
a $4 VPS, a home server. Example systemd unit:

```ini
# /etc/systemd/system/watch-tracker.service
[Unit]
Description=Watch Tracker
After=network-online.target

[Service]
WorkingDirectory=/opt/watch-tracker
ExecStart=/opt/watch-tracker/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
EnvironmentFile=/opt/watch-tracker/.env

[Install]
WantedBy=multi-user.target
```

Notes for hosted platforms: the app is a single process (web + scheduler
together) with a SQLite file, so run **one instance** with a persistent disk.
Platforms that sleep free-tier apps (Render free, etc.) will pause checking
while asleep.

## API

Read-only JSON endpoints for future integrations:

- `GET /api/sites` — tracked sites and their status
- `GET /api/events?limit=50` — recent events
- `GET /healthz` — liveness

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers the Shopify diff logic (drop/restock/price/removal), the HTML
text-diffing, and end-to-end checks against a mocked store, including email
dispatch and error handling.

## Project layout

```
app/
  main.py         FastAPI app, routes, seeding
  cron.py         one-shot mode for GitHub Actions: check all sites + build static dashboard
  checker.py      one check run: fetch → diff → events → email
  scheduler.py    background sweep for due sites (every 60s)
  notifier.py     SMTP email building/sending
  db.py           SQLite schema + queries
  watchers/
    shopify.py    products.json catalog diffing
    html_watcher.py  visible-text diffing for any site
  templates/, static/   dashboard UI
tests/
```
