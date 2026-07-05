"""
SundayFringe Review Tracker — GitHub Actions Edition
-----------------------------------------------------
Runs entirely on GitHub's free servers via GitHub Actions. No PythonAnywhere
account, no Google billing account, no card required, nothing to install or
run on your own computer.

What it does each time it runs:
  1. Loads the list of C venues shows from data/shows.json
  2. Searches DuckDuckGo for each show title, then keeps only results from
     ~35 trusted Fringe review sites (Broadway Baby, FringeReview,
     ThreeWeeks and more) — no API key or account needed at all
  3. Adds any newly-found reviews to data/reviews.json
  4. Updates data/status.json with a timestamp and summary — this is your
     "is it working" check. Open that file in GitHub any time to see the
     last run time, how many shows were checked, and how many new reviews
     were found.

GitHub Actions runs this automatically on the schedule set in
.github/workflows/track-reviews.yml (default: once a day). You never need
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
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

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
# Optional — only needed if you want the Google Sheets export for staff access
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
SHEET_HEADERS = ["Date Found", "Show Title", "Venue", "Company", "Review Source", "Snippet", "URL", "Stars"]

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
REVIEW_SITES_SET = set(REVIEW_SITES)

# DuckDuckGo doesn't handle a single giant "site:a OR site:b OR ... OR site:z"
# query reliably (Google's Custom Search API could, this can't). Splitting
# the 35 sites into smaller groups and running one restricted query per group
# gets much closer to Google's precision — each query only asks DuckDuckGo to
# look inside a handful of domains, rather than hoping a review ranks in an
# unrestricted general search.
SITE_GROUP_SIZE = 9


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


SITE_GROUPS = _chunk(REVIEW_SITES, SITE_GROUP_SIZE)

# ── Batch rotation ───────────────────────────────────────────────────────────
# Each show now takes ~4 requests (one per site group) instead of 1, so batches
# need to be smaller to keep run time reasonable and avoid hammering DuckDuckGo.
BATCH_SIZE = 45


def select_todays_batch(shows: list[dict]) -> list[dict]:
    if not shows:
        return shows
    num_batches = max(1, -(-len(shows) // BATCH_SIZE))  # ceil division
    day_index = datetime.now(timezone.utc).timetuple().tm_yday
    batch_num = day_index % num_batches
    # interleaved slice so each day's batch spans the whole alphabet,
    # not just one contiguous chunk of it
    batch = shows[batch_num::num_batches]
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
DDG_URL = "https://html.duckduckgo.com/html/"
DDG_HEADERS = {
    # A normal browser user-agent — DuckDuckGo's HTML endpoint is more likely
    # to respond normally to requests that look like an ordinary browser visit.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _domain_from_url(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _matches_review_site(domain: str) -> str:
    """Returns the matching review site if this domain is one we trust, else ''."""
    for site in REVIEW_SITES_SET:
        if domain == site or domain.endswith("." + site):
            return site
    return ""


def _run_ddg_query(query: str) -> tuple[list[dict], bool]:
    """Runs one DuckDuckGo query and returns (raw results, succeeded)."""
    try:
        resp = requests.post(
            DDG_URL,
            data={"q": query},
            headers=DDG_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Query failed: '{query[:80]}...': {e}")
        return [], False

    soup = BeautifulSoup(resp.text, "lxml")
    found = []

    for result_div in soup.select(".result"):
        link_tag = result_div.select_one(".result__a")
        snippet_tag = result_div.select_one(".result__snippet")
        if not link_tag or not link_tag.get("href"):
            continue

        raw_href = link_tag["href"]
        # DuckDuckGo's HTML results wrap the real URL inside a redirect link
        # like //duckduckgo.com/l/?uddg=<encoded real url>&... — unwrap it.
        real_url = raw_href
        if "uddg=" in raw_href:
            parsed_qs = parse_qs(urlparse(raw_href).query)
            if "uddg" in parsed_qs:
                real_url = unquote(parsed_qs["uddg"][0])

        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
        found.append({"url": real_url, "snippet": snippet})

    return found, True


def search_for_reviews(show: dict) -> tuple[list[dict], bool]:
    """
    Runs several DuckDuckGo searches per show — one per group of ~9 review
    sites — each restricted with 'site:a OR site:b OR ...'. This is closer to
    the domain-restricted precision Google's Custom Search API gave us,
    without needing an API key, billing account, or card.

    Returns (results, succeeded). succeeded is False only if every one of
    the sub-queries failed outright (network error, blocked, etc.) — partial
    failures still return whatever results the working sub-queries found.
    """
    title = show["title"]
    all_results = []
    seen_result_urls = set()
    any_succeeded = False

    for group in SITE_GROUPS:
        site_clause = " OR ".join(f"site:{s}" for s in group)
        query = f'"{title}" {site_clause}'

        found, succeeded = _run_ddg_query(query)
        if succeeded:
            any_succeeded = True

        for item in found:
            if item["url"] in seen_result_urls:
                continue
            seen_result_urls.add(item["url"])

            domain = _domain_from_url(item["url"])
            matched_site = _matches_review_site(domain)
            if not matched_site:
                continue  # DuckDuckGo ignored the site: restriction — discard

            all_results.append({
                "url": item["url"],
                "source": matched_site,
                "snippet": item["snippet"],
                "stars": extract_stars(item["snippet"]),
            })

        time.sleep(1.2)  # be polite between sub-queries too, not just between shows

    return all_results, any_succeeded


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

        time.sleep(0.8)  # a little extra breathing room between shows

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
