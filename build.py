#!/usr/bin/env python3
"""
Rebuilds index.html with fresh wildfire headlines.
Runs daily via GitHub Actions. Uses only the Python standard library.
"""

import html
import json
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

    Confirmed response shape (from a live call, 31 Jul 2026): a flat JSON list,
    one row per department, with fields:
        reference_time  -- ISO timestamp the whole bulletin was issued
        dep_code        -- two-digit department code, e.g. '31'
        dep_nom         -- department name, e.g. 'Haute-Garonne'
        niveau_j1       -- danger level (1-4) for the day AFTER reference_time
        niveau_j2       -- danger level (1-4) for two days after reference_time
    There is no per-row date -- J1/J2 are relative to reference_time, so the
    date each level applies to has to be computed here.

    Requires a free Meteo-France API key in the METEOFRANCE_API_KEY env var.
    Without a key, or if nothing matches today exactly, returns (None, None)
    and the page shows the level as unconfirmed -- never guessed.
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

    today = datetime.now(timezone(timedelta(hours=2))).date()

    try:
        import json
        rows = json.loads(raw)
        if not isinstance(rows, list):
            rows = rows.get("data", rows.get("features", []))
    except Exception as e:
        print(f"  ! risk level response unreadable as JSON: {e}")
        return None, None

    if not rows:
        print("  ! risk level response had no rows")
        return None, None

    for row in rows:
        if str(row.get("dep_code", "")).strip().lstrip("0") != "31":
            continue

        ref_raw = row.get("reference_time")
        try:
            ref_date = datetime.fromisoformat(str(ref_raw).replace("Z", "+00:00")).date()
        except Exception:
            print(f"  ! risk level: unparseable reference_time {ref_raw!r}")
            return None, None

        j1_date = ref_date + timedelta(days=1)
        j2_date = ref_date + timedelta(days=2)
        print(f"  i dept 31 bulletin issued {ref_date}: "
              f"J1={j1_date} niveau={row.get('niveau_j1')!r}, "
              f"J2={j2_date} niveau={row.get('niveau_j2')!r} (today={today})")

        if j1_date == today:
            lvl_val = row.get("niveau_j1")
        elif j2_date == today:
            lvl_val = row.get("niveau_j2")
        else:
            print("  i no bulletin day (J1/J2) matches today - left unconfirmed")
            return None, None

        try:
            lvl = int(lvl_val)
        except (TypeError, ValueError):
            print(f"  ! risk level: non-numeric level value {lvl_val!r}")
            return None, None

        if 1 <= lvl <= 4:
            print(f"  + risk level for dept 31, {today}: {lvl}")
            return today.isoformat(), lvl

        print(f"  ! risk level: value {lvl} out of expected 1-4 range")
        return None, None

    print("  ! dept-31 row not found in response - left unconfirmed")
    return None, None


FLIGHTS = [
    {"num": "SN2260", "date": "2026-07-31"},
    {"num": "SN3675", "date": "2026-07-31"},
    {"num": "SN3676", "date": "2026-08-08"},
    {"num": "SN2257", "date": "2026-08-08"},
]
FLIGHT_HOST = "aerodatabox.p.rapidapi.com"


def fetch_flight(flight_num, date_str, key):
    url = f"https://{FLIGHT_HOST}/flights/number/{flight_num}/{date_str}"
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key": key, "X-RapidAPI-Host": FLIGHT_HOST, "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        import json
        return json.loads(r.read())


def normalise_flight_status(raw_status):
    if not raw_status:
        return "unknown"
    s = str(raw_status).strip().lower()
    mapping = {
        "scheduled": "scheduled", "expected": "scheduled",
        "on time": "ontime", "ontime": "ontime", "delayed": "delayed",
        "departed": "departed", "en-route": "enroute", "enroute": "enroute",
        "arrived": "landed", "landed": "landed",
        "cancelled": "cancelled", "canceled": "cancelled", "diverted": "diverted",
    }
    return mapping.get(s, "unknown")


def extract_flight(payload, flight_num):
    candidates = payload if isinstance(payload, list) else [payload]
    for entry in candidates:
        num = (entry.get("number") or entry.get("flightNumber") or entry.get("callSign") or "")
        if flight_num.replace(" ", "") not in str(num).replace(" ", "").upper():
            continue
        dep = entry.get("departure", {}) or {}
        arr = entry.get("arrival", {}) or {}

        def time_of(node):
            for k in ("actualTime", "runwayTime", "estimatedTime", "scheduledTime"):
                v = node.get(k)
                if isinstance(v, dict):
                    v = v.get("local") or v.get("utc")
                if v:
                    return str(v)[11:16]
            return None

        delay = None
        try:
            sched = dep.get("scheduledTime", {}).get("local")
            actual = dep.get("actualTime", {}).get("local") or dep.get("estimatedTime", {}).get("local")
            if sched and actual:
                t1 = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(actual.replace("Z", "+00:00"))
                mins = int((t2 - t1).total_seconds() / 60)
                if mins > 5:
                    delay = mins
        except Exception:
            pass

        return {
            "status": normalise_flight_status(entry.get("status") or entry.get("state")),
            "delayMinutes": delay,
            "actualDep": time_of(dep), "actualArr": time_of(arr),
            "gate": dep.get("gate"), "terminal": dep.get("terminal"),
        }
    return None


def fetch_flight_with_retry(flight_num, date_str, key, attempts=3):
    """
    AeroDataBox's free tier rate-limits aggressively -- calling two flights
    back-to-back can 429 the second one immediately. Retry with backoff
    before giving up, and always sleep between calls regardless of outcome.
    """
    import time
    import urllib.error

    last_err = None
    for attempt in range(attempts):
        try:
            return fetch_flight(flight_num, date_str, key)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = 3 * (attempt + 1)
                print(f"    (429 rate limited, waiting {wait}s before retry)")
                time.sleep(wait)
                continue
            raise
    raise last_err


def collect_flights():
    """
    Only calls the flight API on/near the two actual travel dates, to avoid
    burning free-tier quota on the many days this script runs just for the
    fire data. Returns {} (leaving cards as "Not yet checked") otherwise.
    """
    import os
    import time
    key = os.environ.get("AERODATABOX_API_KEY", "").strip()
    if not key:
        print("  i no AERODATABOX_API_KEY set - flight cards stay 'not yet checked'")
        return {}

    today = datetime.now(timezone(timedelta(hours=2))).date().isoformat()
    relevant = [f for f in FLIGHTS if f["date"] == today]
    if not relevant:
        print(f"  i no tracked flights on {today} - skipping flight API calls")
        return {}

    out = {}
    for i, f in enumerate(relevant):
        if i > 0:
            time.sleep(2)  # space out calls; free tier rejects rapid-fire requests
        try:
            payload = fetch_flight_with_retry(f["num"], f["date"], key)
            result = extract_flight(payload, f["num"])
            if result:
                out[f["num"]] = result
                print(f"  + flight {f['num']}: {result['status']}")
            else:
                print(f"  ! flight {f['num']}: no matching entry in response")
        except Exception as e:
            print(f"  ! flight {f['num']} fetch failed: {e}")
    return out


def main():
    print("Fetching feeds...")
    items = collect()
    print(f"Total: {len(items)} headlines")

    risk_date, risk_level = fetch_risk_level()
    flights = collect_flights()

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
    #
    # NOTE: these are plain HTML attributes, NOT comment markers. HTML comments
    # are not parsed inside attribute values -- an earlier version used
    # data-risk-date="<!--MARKER-->value<!--MARKER-->" and the browser read the
    # whole literal string including the comment syntax, so the date never
    # matched and the scale always showed "unconfirmed".
    if risk_date and risk_level:
        page = re.sub(r'data-risk-date="[^"]*"',
                      lambda _: f'data-risk-date="{risk_date}"', page)
        page = re.sub(r'data-risk-level="[^"]*"',
                      lambda _: f'data-risk-level="{risk_level}"', page)

    # Flight statuses. Only stamp "flight-built" when at least one flight was
    # actually resolved this run, so the freshness chip reflects real checks,
    # not just the fire-data build cadence.
    page = re.sub(r"FLIGHT_DATA_START[\s\S]*?FLIGHT_DATA_END",
                  lambda _: f"FLIGHT_DATA_START\n    {json.dumps(flights)}\n    FLIGHT_DATA_END",
                  page)
    if flights:
        page = re.sub(r'data-flight-built="[^"]*"',
                      lambda _: f'data-flight-built="{iso}"',
                      page)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Built at {stamp}")


if __name__ == "__main__":
    main()
