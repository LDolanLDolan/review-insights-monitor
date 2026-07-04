"""
SundayFringe Review Tracker — GitHub Actions Edition
-----------------------------------------------------
Runs entirely on GitHub's free servers via GitHub Actions. No PythonAnywhere
account, no Google Sheets, no monthly fee, and nothing to install or run
on your own computer.

What it does each time it runs:
  1. Loads the list of C venues shows from data/shows.json
  2. Searches ~35 Fringe review sites (Broadway Baby, FringeReview,
     ThreeWeeks and more) for mentions of each show title, using Google's
     free Custom Search API
  3. Adds any newly-found reviews to data/reviews.json
  4. Updates data/status.json with a timestamp and summary — this is your
     "is it working" check. Open that file in GitHub any time to see the
     last run time, how many shows were checked, and how many new reviews
     were found.

GitHub Actions runs this automatically on the schedule set in
.github/workflows/track-reviews.yml (default: twice a day). You never need
to run this file yourself, but you can with:  python fringe_tracker.py
"""

import json
import os
import re
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Paths (all relative to the repo root) ──────────────────────────────────
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
SHOWS_PATH = DATA_DIR / "shows.json"
REVIEWS_PATH = DATA_DIR / "reviews.json"
STATUS_PATH = DATA_DIR / "status.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config from GitHub Secrets (set once in repo Settings > Secrets) ───────
GOOGLE_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_CX = os.environ.get("GOOGLE_SEARCH_CX", "")
SEARCH_API_URL = "https://www.googleapis.com/customsearch/v1"

# ── Review sites to search across ───────────────────────────────────────────
REVIEW_SITES = [
    # Major outlets
    "scotsman.com", "theguardian.com", "timeout.com", "thestage.co.uk",
    "whatsonstage.com", "exeuntmagazine.com", "fest-mag.com", "theskinny.co.uk",
    "chortle.co.uk", "broadwaybaby.com", "britishcomedyguide.co.uk",
    "totaltheatre.org.uk", "theupcoming.co.uk",
    # Mid-tier reliable
    "fringereview.co.uk", "theweerev.com", "edfringereview.com",
    "theatreweekly.com", "theatreandtonic.com", "one4review.co.uk",
    "voicemag.uk", "theatrescotland.com", "threeweeeks.co.uk",
    "westendbestfriend.com",
    # Smaller blogs — most likely to cover emerging/overlooked shows
    "loureviews.co.uk", "fringebiscuit.com", "lostintheatreland.co.uk",
    "katmasterson.com", "corrblimey.co.uk", "clownster.co.uk",
    "lisainthetheatre.com", "bingefringereviews.com", "fromnorth.co.uk",
    "glasgowtheatreblog.co.uk", "louderthanwar.com",
]
SITE_RESTRICT = " OR ".join(f"site:{s}" for s in REVIEW_SITES)


# ── Helpers ──────────────────────────────────────────────────────────────────
def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def extract_stars(text: str) -> str:
    stars = re.findall(r"[★✭✩⭐]{1,5}", text)
    if stars:
        return stars[0]
    m = re.search(r"\b([1-5])\s*/\s*5\b|\b([1-5])\s+stars?\b", text, re.IGNORECASE)
    return m.group(0) if m else ""


# ── Show list ────────────────────────────────────────────────────────────────
def load_shows() -> list[dict]:
    """
    Reads data/shows.json — a simple list you maintain yourself, e.g.:
    [
      {"title": "A Jaffa Cake Musical", "company": "Gigglemug Theatre"},
      {"title": "Locusts", "company": "Orange Works"}
    ]
    This is deliberately manual rather than scraped, because the C venues
    booking site renders its listings with JavaScript, which makes reliable
    automated scraping fragile. Paste in your show list once at the start
    of the run and the tracker does the rest.
    """
    shows = load_json(SHOWS_PATH, [])
    if not shows:
        log.warning(
            "data/shows.json is empty. Add your show list there — "
            "see data/shows.json for the format."
        )
    else:
        log.info(f"Loaded {len(shows)} shows from data/shows.json")
    return shows


# ── Searching ────────────────────────────────────────────────────────────────
def search_for_reviews(show: dict) -> list[dict]:
    """Searches Google Custom Search, restricted to REVIEW_SITES, for a show title."""
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        log.error("Missing GOOGLE_SEARCH_API_KEY or GOOGLE_SEARCH_CX secret.")
        return []

    title = show["title"]
    query = f'"{title}" ({SITE_RESTRICT})'
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
        "q": query,
        "num": 10,
    }

    try:
        resp = requests.get(SEARCH_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.error(f"Search failed for '{title}': {e}")
        return []

    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", "")
        results.append({
            "url": item.get("link", ""),
            "source": item.get("displayLink", ""),
            "snippet": snippet,
            "stars": extract_stars(snippet),
        })
    return results


# ── Main run ─────────────────────────────────────────────────────────────────
def main():
    shows = load_shows()
    reviews = load_json(REVIEWS_PATH, [])
    seen_urls = {url_hash(r["url"]) for r in reviews}

    new_count = 0
    searched_count = 0

    for show in shows:
        title = show.get("title", "").strip()
        if not title:
            continue

        log.info(f"Searching: {title}")
        results = search_for_reviews(show)
        searched_count += 1

        for result in results:
            uid = url_hash(result["url"])
            if uid in seen_urls:
                continue
            reviews.append({
                "date_found": datetime.now(timezone.utc).isoformat(),
                "show_title": title,
                "company": show.get("company", ""),
                "venue": show.get("venue", ""),
                "review_source": result["source"],
                "snippet": result["snippet"],
                "url": result["url"],
                "stars": result["stars"],
            })
            seen_urls.add(uid)
            new_count += 1
            log.info(f"  New review found: {result['url']}")

        time.sleep(1.2)  # be polite to the search API

    save_json(REVIEWS_PATH, reviews)

    status = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "shows_loaded": len(shows),
        "shows_searched": searched_count,
        "new_reviews_this_run": new_count,
        "total_reviews_tracked": len(reviews),
        "status": "ok" if searched_count > 0 else "no shows loaded — check data/shows.json",
    }
    save_json(STATUS_PATH, status)

    log.info(
        f"Done. Checked {searched_count} shows, found {new_count} new review(s). "
        f"Total tracked: {len(reviews)}."
    )


if __name__ == "__main__":
    main()
