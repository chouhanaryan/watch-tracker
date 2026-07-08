"""Email notifications over SMTP."""

import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config

log = logging.getLogger(__name__)

KIND_LABELS = {
    "new_drop": "NEW DROP",
    "restock": "Back in stock",
    "sold_out": "Sold out",
    "price_change": "Price change",
    "product_change": "Product updated",
    "product_removed": "Product removed",
    "page_change": "Page updated",
    "unlisted_link": "Possible new listing",
}


def build_subject(site_name: str, events: list[dict]) -> str:
    drops = [e for e in events if e["kind"] == "new_drop"]
    if drops:
        if len(drops) == 1:
            return f"\U0001f6a8 NEW DROP at {site_name}: {drops[0]['title'].removeprefix('New product: ')}"
        return f"\U0001f6a8 NEW DROP at {site_name}: {len(drops)} new products"
    links = [e for e in events if e["kind"] == "unlisted_link"]
    if links:
        return f"\U0001f440 Possible new listing at {site_name} — not yet in the catalog"
    return f"⏰ {site_name} updated ({len(events)} change{'s' if len(events) != 1 else ''})"


def build_html_body(site_name: str, events: list[dict]) -> str:
    rows = []
    for e in events:
        label = KIND_LABELS.get(e["kind"], e["kind"])
        color = ("#d0342c" if e["kind"] == "new_drop"
                 else "#2c6e49" if e["kind"] == "restock"
                 else "#8a63d2" if e["kind"] == "unlisted_link"
                 else "#555")
        details = html.escape(e.get("details") or "").replace("\n", "<br>")
        link = (
            f'<a href="{html.escape(e["url"], quote=True)}">View →</a>'
            if e.get("url") else ""
        )
        rows.append(
            f'<div style="margin:0 0 16px;padding:12px 16px;border-left:4px solid {color};'
            f'background:#f7f7f7;border-radius:4px;">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:1px;color:{color};'
            f'text-transform:uppercase;">{label}</div>'
            f'<div style="font-size:16px;font-weight:600;margin:4px 0;">{html.escape(e["title"])}</div>'
            f'<div style="font-size:13px;color:#555;">{details}</div>'
            f'<div style="margin-top:6px;font-size:13px;">{link}</div>'
            f"</div>"
        )
    return (
        f'<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        f'max-width:560px;margin:0 auto;padding:24px;">'
        f'<h2 style="margin:0 0 4px;">{html.escape(site_name)}</h2>'
        f'<p style="margin:0 0 20px;color:#777;font-size:13px;">'
        f"Watch Tracker spotted {len(events)} change{'s' if len(events) != 1 else ''}.</p>"
        f"{''.join(rows)}"
        f'<p style="color:#aaa;font-size:11px;margin-top:24px;">Sent by Watch Tracker</p>'
        f"</div>"
    )


def build_text_body(site_name: str, events: list[dict]) -> str:
    lines = [f"{site_name}: {len(events)} change(s) detected", ""]
    for e in events:
        label = KIND_LABELS.get(e["kind"], e["kind"])
        lines.append(f"[{label}] {e['title']}")
        if e.get("details"):
            lines.append(f"  {e['details']}")
        if e.get("url"):
            lines.append(f"  {e['url']}")
        lines.append("")
    return "\n".join(lines)


def send_event_email(site_name: str, events: list[dict], recipients: list[str]) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = build_subject(site_name, events)
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(build_text_body(site_name, events), "plain", "utf-8"))
    msg.attach(MIMEText(build_html_body(site_name, events), "html", "utf-8"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
        server.ehlo()
        if server.has_extn("starttls"):
            server.starttls()
            server.ehlo()
        if config.SMTP_USER and config.SMTP_PASSWORD:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.EMAIL_FROM, recipients, msg.as_string())
    log.info("Sent notification email to %s (%d events)", recipients, len(events))
