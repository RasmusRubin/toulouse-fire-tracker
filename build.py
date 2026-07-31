#!/usr/bin/env python3
"""
Rebuilds index.html with fresh wildfire headlines.
Runs daily via GitHub Actions. Uses only the Python standard library.
"""

import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# Google News RSS. Server-side fetch, so no CORS problems.
FEEDS = [
    ("Haute-Garonne (FR)",
     "https://news.google.com/rss/search?q=incendie+Haute-Garonne+OR+Toulouse+feu+de+for%C3%AAt&hl=fr&gl=FR&ceid=FR:fr"),
    ("Occitanie (FR)",
     "https://news.google.com/rss/search?q=feux+de+for%C3%AAt+Occitanie&hl=fr&gl=FR&ceid=FR:fr"),
    ("France (EN)",
     "https://news.google.com/rss/search?q=France+wildfire+Toulouse+OR+Gironde&hl=en-GB&gl=GB&ceid=GB:en"),
]

MAX_PER_FEED = 4
MAX_AGE_DAYS = 5
UA = "Mozilla/5.0 (compatible; fire-tracker/1.0)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def parse_date(text):
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            d = datetime.strptime(text, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def collect():
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    items, seen = [], set()

    for label, url in FEEDS:
        try:
            root = ET.fromstring(fetch(url))
        except Exception as e:
            print(f"  ! {label} failed: {e}", file=sys.stderr)
            continue

        count = 0
        for item in root.iter("item"):
            if count >= MAX_PER_FEED:
                break
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link or title in seen:
                continue

            pub = parse_date(item.findtext("pubDate"))
            if pub and pub < cutoff:
                continue

            source = item.findtext("{*}source") or ""
            src_el = item.find("source")
            if src_el is not None and src_el.text:
                source = src_el.text
            # Google News appends " - Source" to titles; split it off.
            if not source and " - " in title:
                title, source = title.rsplit(" - ", 1)

            seen.add(title)
            items.append({
                "title": title,
                "link": link,
                "source": source or label,
                "date": pub,
                "feed": label,
            })
            count += 1
        print(f"  + {label}: {count} items")

    items.sort(key=lambda i: i["date"] or datetime.min.replace(tzinfo=timezone.utc),
               reverse=True)
    return items


def render(items):
    if not items:
        return ('<ul class="news-list"><li><p>No headlines retrieved on the last '
                'run. Use the official map links above.</p></li></ul>')

    rows = []
    for i in items:
        when = i["date"].strftime("%d %b, %H:%M") if i["date"] else ""
        meta = html.escape(i["source"])
        if when:
            meta += f" &middot; {when}"
        rows.append(
            '      <li>\n'
            f'        <span class="src">{meta}</span>\n'
            f'        <a href="{html.escape(i["link"], quote=True)}" '
            f'target="_blank" rel="noopener">{html.escape(i["title"])}</a>\n'
            f'        <p>{html.escape(i["feed"])}</p>\n'
            '      </li>'
        )
    return '<ul class="news-list">\n' + "\n".join(rows) + '\n    </ul>'


def swap(text, start, end, payload):
    return re.sub(
        f"{re.escape(start)}.*?{re.escape(end)}",
        lambda _: f"{start}\n    {payload}\n    {end}",
        text, flags=re.S,
    )


def fetch_risk_level():
    """
    Fetch today's Meteo des forets danger level for Haute-Garonne (dept 31).

    Returns (iso_date, level 1-4) or (None, None).

    Endpoint confirmed from the Meteo-France API portal (DonneesPubliquesMeteoForets,
    v1): GET /carte/departement/encours on host
    https://public-api.meteofrance.fr/public/DPMeteoForets/v1
    Returns the current departmental map as CSV or JSON.

    Requires a free Meteo-France API key in the METEOFRANCE_API_KEY env var
    (set as a GitHub Actions secret). Without a key this returns None and the
    page falls back to showing "level not confirmed today" -- correct
    behaviour, not a failure. Never guess a level: a wrong level is worse
    than an absent one.

    NOTE: the exact response shape (JSON field names, or CSV-only) was not
    verified against a live call while writing this -- only the endpoint path
    and general product description were available. Check the first Action
    run's log; if parsing fails it will say so explicitly, and the field
    names/parsing below are the first thing to adjust.
    """
    import os
    key = os.environ.get("METEOFRANCE_API_KEY", "").strip()
    if not key:
        print("  i no METEOFRANCE_API_KEY set - risk level left unconfirmed")
        return None, None

    base = "https://public-api.meteofrance.fr/public/DPMeteoForets/v1"
    url = f"{base}/carte/departement/encours?format=json"

    try:
        req = urllib.request.Request(url, headers={"apikey": key, "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except Exception as e:
        print(f"  ! risk level fetch failed: {e}")
        return None, None

    today = datetime.now(timezone(timedelta(hours=2))).date().isoformat()

    # Try JSON first; fall back to CSV if the API only returns that format
    # regardless of the query parameter.
    rows = None
    try:
        import json
        parsed = json.loads(raw)
        rows = parsed if isinstance(parsed, list) else parsed.get("data", parsed.get("features", []))
    except Exception:
        try:
            import csv, io
            text = raw.decode("utf-8-sig", errors="replace")
            delim = ";" if text.count(";") > text.count(",") else ","
            rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
        except Exception as e:
            print(f"  ! risk level response unreadable as JSON or CSV: {e}")
            return None, None

    if not rows:
        print("  ! risk level response had no rows")
        return None, None

    def get_field(row, *names):
        for n in names:
            for k in row.keys():
                if k.lower().replace(" ", "").replace("_", "") == n:
                    return row[k]
        return None

    for row in rows:
        props = row.get("properties", row) if isinstance(row, dict) else row
        dept = get_field(props, "departement", "coddep", "codedepartement", "insee", "dep")
        if dept is None:
            continue
        if str(dept).strip().lstrip("0") not in ("31",):
            continue

        date_val = get_field(props, "date", "datej1", "jour")
        lvl_val = get_field(props, "niveau", "niveaudanger", "niveauj1", "level", "danger")

        date_str = str(date_val)[:10] if date_val else None
        try:
            lvl = int(lvl_val)
        except (TypeError, ValueError):
            continue

        if date_str == today and 1 <= lvl <= 4:
            print(f"  + risk level for dept 31, {today}: {lvl}")
            return today, lvl

    print("  i no matching dept-31 row for today - left unconfirmed")
    return None, None


def main():
    print("Fetching feeds...")
    items = collect()
    print(f"Total: {len(items)} headlines")

    risk_date, risk_level = fetch_risk_level()

    paris = timezone(timedelta(hours=2))  # CEST; use +1 in winter
    now = datetime.now(paris)
    stamp = now.strftime("%a %d %b %Y, %H:%M") + " Paris"
    iso = now.isoformat()

    with open("index.html", encoding="utf-8") as f:
        page = f.read()

    page = swap(page, "<!--FEED_START-->", "<!--FEED_END-->", render(items))
    page = re.sub(
        r"<!--STAMP_START-->.*?<!--STAMP_END-->",
        lambda _: f"<!--STAMP_START-->{stamp}<!--STAMP_END-->",
        page, flags=re.S,
    )
    # Machine-readable build time, used by the page to show its own age.
    page = re.sub(
        r'data-built="[^"]*"',
        lambda _: f'data-built="{iso}"',
        page,
    )

    # Risk level. Only written when genuinely fetched for today; otherwise the
    # existing (older) date stays put and the page greys the scale out by itself.
    if risk_date and risk_level:
        page = re.sub(r"<!--RISKDATE_START-->.*?<!--RISKDATE_END-->",
                      lambda _: f"<!--RISKDATE_START-->{risk_date}<!--RISKDATE_END-->",
                      page, flags=re.S)
        page = re.sub(r"<!--RISKLEVEL_START-->.*?<!--RISKLEVEL_END-->",
                      lambda _: f"<!--RISKLEVEL_START-->{risk_level}<!--RISKLEVEL_END-->",
                      page, flags=re.S)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Built at {stamp}")


if __name__ == "__main__":
    main()
