"""
SundayFringe Review Tracker — GitHub Actions Edition
-----------------------------------------------------
Runs entirely on GitHub's free servers via GitHub Actions. No PythonAnywhere
account, no manual runs on your own computer.

Uses Google's Custom Search API, restricted to ~35 trusted Fringe review
sites. This needs a Google Cloud billing account on file (identity
verification only — see the three safeguards below), but stays comfortably
inside the free 100 queries/day tier every single run.

Three independent safety nets against ever being charged:
  1. HARD_SAFETY_CAP below — this script will never send more than this many
     search requests in one run, no matter what BATCH_SIZE is set to.
  2. Google's own quota system rejects anything over 100/day with an error —
     it does not silently bill you for the overage.
  3. A £1 budget alert on the Google Cloud project — see SETUP.md.
All three would have to fail at once for an unexpected charge to occur.

What it does each time it runs:
  1. Loads the list of C venues shows from data/shows.json
  2. Searches Google Custom Search, restricted to our trusted review sites,
     for each show in today's batch
  3. Adds any newly-found reviews to data/reviews.json
  4. Updates data/status.json with a timestamp and summary — this is your
     "is it working" check.

GitHub Actions runs this automatically on the schedule set in
.github/workflows/track-reviews.yml. You never need to run this file
yourself, but you can with:  python fringe_tracker.py
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

# Google Sheets is optional — only used if the two secrets below are set.
try:
    import gspread
    from google.oauth2.service_account import Credentials
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False

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

# Optional — only needed if you want the Google Sheets export for staff access
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
SHEET_HEADERS = ["Date Found", "Show Title", "Venue", "Company", "Review Source", "Snippet", "URL", "Stars"]

# ── Review sites to search across ───────────────────────────────────────────
REVIEW_SITES = [
    # Major outlets
    "scotsman.com", "theguardian.com", "timeout.com", "thestage.co.uk",
    "whatsonstage.com", "exeuntmagazine.com", "fest-mag.com", "theskinny.co.uk",
    "chortle.co.uk", "broadwaybaby.com", "comedy.co.uk",
    "totaltheatre.org.uk", "theupcoming.co.uk",
    # Mid-tier reliable
    "fringereview.co.uk", "theweereview.com", "edfringereview.com",
    "theatreweekly.com", "theatreandtonic.com", "one4review.co.uk",
    "voicemag.uk", "theatrescotland.com", "threeweeeks.co.uk",
    "westendbestfriend.com",
    # Smaller blogs — most likely to cover emerging/overlooked shows
    "loureviews.blog", "fringebiscuit.com", "lostintheatreland.co.uk",
    "katmasterson.com", "corrblimey.uk", "clownster.co.uk",
    "lisainthetheatre.com", "bingefringereviews.com", "fromnorth.co.uk",
    "glasgowtheatreblog.co.uk", "louderthanwar.com",
]
SITE_RESTRICT = " OR ".join(f"site:{s}" for s in REVIEW_SITES)

# ── Safety cap — this is the hard backstop described at the top of the file.
# Even if BATCH_SIZE below were accidentally set to 1000, this script
# physically will not send more than HARD_SAFETY_CAP search requests in one
# run. Deliberately set well under Google's 100/day free limit.
HARD_SAFETY_CAP = 90

# ── Batch rotation ───────────────────────────────────────────────────────────
# One request per show (Google's API handles the big site: OR clause in a
# single query, unlike DuckDuckGo). Batches stay under the free 100/day cap.
BATCH_SIZE = 90


def select_todays_batch(shows: list[dict]) -> list[dict]:
    if not shows:
        return shows
    num_batches = max(1, -(-len(shows) // BATCH_SIZE))  # ceil division
    day_index = datetime.now(timezone.utc).timetuple().tm_yday
    batch_num = day_index % num_batches
    # interleaved slice so each day's batch spans the whole alphabet,
    # not just one contiguous chunk of it
    batch = shows[batch_num::num_batches]
    if len(batch) > HARD_SAFETY_CAP:
        log.warning(
            f"Batch of {len(batch)} exceeds the hard safety cap of "
            f"{HARD_SAFETY_CAP} — trimming to stay under it."
        )
        batch = batch[:HARD_SAFETY_CAP]
    log.info(
        f"Batch {batch_num + 1} of {num_batches} today — "
        f"checking {len(batch)} of {len(shows)} shows "
        f"(full list covered roughly every {num_batches} day(s))"
    )
    return batch


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
def search_for_reviews(show: dict) -> tuple[list[dict], bool]:
    """
    Searches Google Custom Search, restricted to REVIEW_SITES, for a show
    title. Returns (results, succeeded) — succeeded is False if the request
    itself failed (network error, quota exhausted, etc.).
    """
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        log.error("Missing GOOGLE_SEARCH_API_KEY or GOOGLE_SEARCH_CX secret.")
        return [], False

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
        return [], False

    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", "")
        results.append({
            "url": item.get("link", ""),
            "source": item.get("displayLink", ""),
            "snippet": snippet,
            "stars": extract_stars(snippet),
        })
    return results, True


# ── Google Sheets export (optional, for staff access) ───────────────────────
def get_sheet():
    """Returns a gspread worksheet object, or None if Sheets isn't configured."""
    if not SHEETS_AVAILABLE:
        log.info("gspread not installed — skipping Sheets export.")
        return None
    if not GOOGLE_SHEETS_CREDENTIALS or not GOOGLE_SHEET_ID:
        log.info("Google Sheets secrets not set — skipping Sheets export.")
        return None

    try:
        creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"],
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
        return sheet
    except Exception as e:
        log.error(f"Could not connect to Google Sheet: {e}")
        return None


def ensure_headers(sheet):
    first_row = sheet.row_values(1)
    if first_row != SHEET_HEADERS:
        sheet.clear()
        sheet.append_row(SHEET_HEADERS)


def append_to_sheet(sheet, review: dict):
    sheet.append_row([
        review["date_found"],
        review["show_title"],
        review.get("venue", ""),
        review.get("company", ""),
        review["review_source"],
        review["snippet"],
        review["url"],
        review["stars"],
    ])


# ── Main run ─────────────────────────────────────────────────────────────────
def main():
    all_shows = load_shows()
    shows = select_todays_batch(all_shows)
    reviews = load_json(REVIEWS_PATH, [])
    seen_urls = {url_hash(r["url"]) for r in reviews}

    sheet = get_sheet()
    if sheet:
        ensure_headers(sheet)
        log.info("Connected to Google Sheet — will mirror new reviews there too.")

    new_count = 0
    searched_count = 0
    failed_count = 0

    for show in shows:
        title = show.get("title", "").strip()
        if not title:
            continue

        log.info(f"Searching: {title}")
        results, succeeded = search_for_reviews(show)
        searched_count += 1
        if not succeeded:
            failed_count += 1

        for result in results:
            uid = url_hash(result["url"])
            if uid in seen_urls:
                continue
            review = {
                "date_found": datetime.now(timezone.utc).isoformat(),
                "show_title": title,
                "company": show.get("company", ""),
                "venue": show.get("venue", ""),
                "review_source": result["source"],
                "snippet": result["snippet"],
                "url": result["url"],
                "stars": result["stars"],
            }
            reviews.append(review)
            seen_urls.add(uid)
            new_count += 1
            log.info(f"  New review found: {result['url']}")

            if sheet:
                try:
                    append_to_sheet(sheet, review)
                except Exception as e:
                    log.error(f"Failed to write to Google Sheet: {e}")

        time.sleep(1.2)  # be polite to the search API

    save_json(REVIEWS_PATH, reviews)

    if searched_count == 0:
        status_text = "no shows loaded — check data/shows.json"
    elif failed_count == searched_count:
        status_text = "all searches failed — check the Actions log for the error"
    elif failed_count > 0:
        status_text = f"ok, but {failed_count} of {searched_count} searches failed"
    else:
        status_text = "ok"

    status = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "total_shows": len(all_shows),
        "shows_in_todays_batch": len(shows),
        "shows_searched": searched_count,
        "searches_failed": failed_count,
        "new_reviews_this_run": new_count,
        "total_reviews_tracked": len(reviews),
        "status": status_text,
    }
    save_json(STATUS_PATH, status)

    log.info(
        f"Done. Checked {searched_count} of {len(all_shows)} total shows "
        f"({failed_count} failed), found {new_count} new review(s). "
        f"Total tracked: {len(reviews)}."
    )


if __name__ == "__main__":
    main()
