#!/usr/bin/env python3
"""
fetch_signals.py
================

Pulls public signals for each Croydon ward and writes a structured
metadata-only JSON to data/ward-signals.json.

Sources:
  - FixMyStreet RSS feed per ward
  - Reddit r/croydon search per ward
  - Inside Croydon WordPress feed (matched to wards by name mention)

Run via GitHub Actions on a 6-hourly schedule. See
.github/workflows/refresh-signals.yml.

This is a Croydon Council Digital & Data Transformation prototype.
Contact: vindy.hansra@croydon.gov.uk
"""

from __future__ import annotations
import json
import sys
import time
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
import feedparser


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

# 28 Croydon wards. Must stay in sync with the prototype.
WARDS: list[str] = [
    "Addiscombe East",
    "Addiscombe West",
    "Bensham Manor",
    "Broad Green",
    "Coulsdon Town",
    "Crystal Palace and Upper Norwood",
    "Fairfield",
    "Kenley",
    "New Addington North",
    "New Addington South",
    "Norbury Park",
    "Norbury and Pollards Hill",
    "Old Coulsdon",
    "Park Hill and Whitgift",
    "Purley Oaks and Riddlesdown",
    "Purley and Woodcote",
    "Sanderstead",
    "Selhurst",
    "Selsdon Vale and Forestdale",
    "Selsdon and Addington Village",
    "Shirley North",
    "Shirley South",
    "South Croydon",
    "South Norwood",
    "Thornton Heath",
    "Waddon",
    "West Thornton",
    "Woodside",
]

# Output path is repo/data/ward-signals.json. Script lives in repo/scripts/.
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "ward-signals.json"

USER_AGENT = (
    "CroydonWardSignalsBot/0.1 "
    "(+https://github.com/; Croydon Council Digital & Data Transformation prototype)"
)

# Time window for inclusion
TIME_WINDOW_DAYS = 30
CUTOFF_DT = datetime.now(timezone.utc) - timedelta(days=TIME_WINDOW_DAYS)

# Per-source limits
MAX_FIXMYSTREET = 10
MAX_REDDIT = 5
MAX_NEWS = 5

# HTTP timeouts and retries
HTTP_TIMEOUT = 20  # seconds
HTTP_RETRIES = 2
POLITE_DELAY = 0.5  # seconds between ward fetches per source


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def http_get(url: str, params: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> requests.Response | None:
    """Resilient HTTP GET. Returns response or None on failure."""
    final_headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en"}
    if headers:
        final_headers.update(headers)
    last_err: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=final_headers, timeout=HTTP_TIMEOUT)
            if r.status_code == 429:
                # Rate-limited; back off
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(1.0 * (attempt + 1))
                continue
            return r
        except (requests.RequestException, OSError) as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    if last_err:
        print(f"    ! HTTP error after retries: {last_err}", file=sys.stderr, flush=True)
    return None


def parse_entry_date(entry: Any) -> datetime | None:
    """Best-effort date parse from a feedparser entry."""
    for key in ("published_parsed", "updated_parsed"):
        v = getattr(entry, key, None) or entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
        if v:
            try:
                return datetime(*v[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def slugify_ward(name: str) -> str:
    """WordPress-style slug for Inside Croydon tag URLs."""
    s = name.lower()
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def url_encode_ward(name: str) -> str:
    """URL path component for FixMyStreet (spaces → +, other chars URL-encoded)."""
    return quote_plus(name)


# ---------------------------------------------------------------------
# FixMyStreet
# ---------------------------------------------------------------------

def fetch_fixmystreet(ward: str) -> list[dict]:
    """Pull recent FixMyStreet reports for a ward from its RSS feed."""
    encoded = url_encode_ward(ward)
    url = f"https://www.fixmystreet.com/rss/reports/Croydon/{encoded}"
    r = http_get(url)
    if r is None or r.status_code != 200:
        return []
    try:
        feed = feedparser.parse(r.content)
    except Exception as e:
        print(f"    ! feedparser error: {e}", file=sys.stderr)
        return []
    items: list[dict] = []
    for entry in feed.entries:
        date = parse_entry_date(entry)
        if date and date < CUTOFF_DT:
            continue
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        # Try to extract a category from the title prefix, e.g. "Pothole - Old Lodge Lane"
        category = None
        if " - " in title:
            possible_cat = title.split(" - ", 1)[0].strip()
            if 2 < len(possible_cat) < 50:
                category = possible_cat
        items.append({
            "title": title,
            "url": link,
            "date": date.isoformat() if date else None,
            "category": category,
        })
        if len(items) >= MAX_FIXMYSTREET:
            break
    return items


# ---------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------

def fetch_reddit(ward: str) -> list[dict]:
    """Search r/croydon for posts mentioning the ward name."""
    # Quote the ward to favour exact-phrase matches; restrict to subreddit.
    url = "https://www.reddit.com/r/croydon/search.json"
    params = {
        "q": f'"{ward}"',
        "restrict_sr": "true",
        "sort": "new",
        "t": "month",
        "limit": 25,
    }
    r = http_get(url, params=params)
    if r is None or r.status_code != 200:
        return []
    try:
        data = r.json()
    except ValueError:
        return []
    posts = data.get("data", {}).get("children", []) or []
    items: list[dict] = []
    for post in posts:
        p = post.get("data", {})
        created = p.get("created_utc")
        if not created:
            continue
        dt = datetime.fromtimestamp(created, tz=timezone.utc)
        if dt < CUTOFF_DT:
            continue
        title = (p.get("title") or "").strip()
        permalink = (p.get("permalink") or "").strip()
        if not title or not permalink:
            continue
        items.append({
            "title": title,
            "url": "https://www.reddit.com" + permalink,
            "date": dt.isoformat(),
            "subreddit": p.get("subreddit") or "croydon",
            "score": int(p.get("score") or 0),
            "num_comments": int(p.get("num_comments") or 0),
        })
    # Sort by score (popularity) then take top N
    items.sort(key=lambda x: (x.get("score", 0), x.get("date") or ""), reverse=True)
    return items[:MAX_REDDIT]


# ---------------------------------------------------------------------
# Inside Croydon (news)
# ---------------------------------------------------------------------

def fetch_inside_croydon_pages(max_pages: int = 4) -> list[dict]:
    """Pull recent posts from Inside Croydon main feed across N pages."""
    all_entries: list[dict] = []
    base = "https://insidecroydon.com/feed/"
    for page in range(1, max_pages + 1):
        url = base if page == 1 else f"{base}?paged={page}"
        r = http_get(url)
        if r is None or r.status_code != 200:
            break
        try:
            feed = feedparser.parse(r.content)
        except Exception:
            break
        if not feed.entries:
            break
        for e in feed.entries:
            date = parse_entry_date(e)
            if date and date < CUTOFF_DT:
                continue
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            # WordPress feeds include tags via `tags` list and `summary`
            tag_terms = []
            for t in (e.get("tags") or []):
                term = (t.get("term") or "").strip()
                if term:
                    tag_terms.append(term)
            summary_text = (e.get("summary") or "")
            # Strip HTML tags from summary for clean keyword matching
            summary_clean = re.sub(r"<[^>]+>", " ", summary_text)
            all_entries.append({
                "title": title,
                "url": link,
                "date": date.isoformat() if date else None,
                "tags": tag_terms,
                "search_blob": (title + " " + summary_clean + " " + " ".join(tag_terms)).lower(),
            })
        time.sleep(0.3)
    return all_entries


def match_news_to_wards(entries: list[dict], wards: list[str]) -> dict[str, list[dict]]:
    """Match Inside Croydon entries to wards by name mention (in title, summary, or tags)."""
    results: dict[str, list[dict]] = {w: [] for w in wards}
    # Lowercase ward names for matching; some need contextual care
    ward_keys = [(w, w.lower()) for w in wards]
    for entry in entries:
        blob = entry["search_blob"]
        for ward_name, ward_lc in ward_keys:
            if ward_lc in blob:
                if len(results[ward_name]) < MAX_NEWS:
                    results[ward_name].append({
                        "title": entry["title"],
                        "url": entry["url"],
                        "date": entry["date"],
                        "publisher": "Inside Croydon",
                    })
    return results


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> int:
    print(f"Fetching ward signals for {len(WARDS)} Croydon wards. Window: last {TIME_WINDOW_DAYS} days.")
    print(f"Cutoff: {CUTOFF_DT.isoformat()}")
    print()

    # News is fetched once across all wards (single feed, then matched).
    print("→ Inside Croydon (one fetch, matched to all wards)...")
    news_entries = fetch_inside_croydon_pages()
    news_by_ward = match_news_to_wards(news_entries, WARDS)
    total_news = sum(len(v) for v in news_by_ward.values())
    print(f"  matched {total_news} news items across wards from {len(news_entries)} recent posts.")
    print()

    # FixMyStreet and Reddit per ward.
    ward_data: dict[str, dict] = {}
    for i, ward in enumerate(WARDS, 1):
        print(f"[{i:2d}/{len(WARDS)}] {ward}", flush=True)

        fix_items = fetch_fixmystreet(ward)
        time.sleep(POLITE_DELAY)
        reddit_items = fetch_reddit(ward)
        time.sleep(POLITE_DELAY)
        news_items = news_by_ward.get(ward, [])

        print(f"    FixMyStreet: {len(fix_items):2d} · Reddit: {len(reddit_items)} · News: {len(news_items)}")

        ward_data[ward] = {
            "fixmystreet": fix_items,
            "reddit": reddit_items,
            "news": news_items,
        }

    output = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
            "schema": "ward-signals-v1",
            "sources": ["fixmystreet", "reddit", "inside-croydon"],
            "time_window_days": TIME_WINDOW_DAYS,
            "ward_count": len(WARDS),
            "note": (
                "Public signals from public sources. Metadata only — no body content. "
                "Nextdoor and private Facebook groups are not accessible. "
                "Officers should triage sensitive content before action."
            ),
        },
        "wards": ward_data,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    total_signals = sum(
        len(v.get("fixmystreet", [])) + len(v.get("reddit", [])) + len(v.get("news", []))
        for v in ward_data.values()
    )
    print()
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Total signals: {total_signals} ({total_news} news, "
          f"{sum(len(v.get('fixmystreet', [])) for v in ward_data.values())} FixMyStreet, "
          f"{sum(len(v.get('reddit', [])) for v in ward_data.values())} Reddit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
