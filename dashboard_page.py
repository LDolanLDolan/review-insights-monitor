"""
Add this as a new page (or a new tab within app.py) in your existing
Streamlit app. It just reads the JSON files GitHub Actions keeps updated —
no scraping, no API calls happen here. This file only displays data.
"""

import json
from pathlib import Path

import streamlit as st
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def show_dashboard():
    st.title("🎭 C Venues Review Tracker")

    status = load_json(DATA_DIR / "status.json", {})
    reviews = load_json(DATA_DIR / "reviews.json", [])
    shows = load_json(DATA_DIR / "shows.json", [])

    # ── Health check panel ──────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    col1.metric("Last checked", status.get("last_run", "never")[:16].replace("T", " ") or "never")
    col2.metric("Shows checked today", status.get("shows_in_todays_batch", 0))
    col3.metric("Reviews found so far", status.get("total_reviews_tracked", 0))

    total = status.get("total_shows", 0)
    if total:
        st.caption(
            f"Rotates through all {total} shows in batches — full list re-checked every few days, "
            f"not all 217 every single run, to stay within the free search quota."
        )

    if status.get("status") not in ("ok", None):
        st.warning(f"Status: {status.get('status')}")

    st.divider()

    # ── Venue filter ─────────────────────────────────────────────────────
    venues = sorted({s.get("venue", "") for s in shows if s.get("venue")})
    selected_venue = st.selectbox("Filter by venue", ["All venues"] + venues)

    if selected_venue == "All venues":
        filtered_shows = shows
    else:
        filtered_shows = [s for s in shows if s.get("venue") == selected_venue]
    filtered_titles = {s["title"] for s in filtered_shows}
    filtered_reviews = [r for r in reviews if r["show_title"] in filtered_titles]

    st.divider()

    # ── Coverage gap: which shows have zero reviews ────────────────────
    reviewed_titles = {r["show_title"] for r in filtered_reviews}
    unreviewed = sorted(filtered_titles - reviewed_titles)

    st.subheader(f"Shows with no reviews yet ({len(unreviewed)} of {len(filtered_titles)})")
    if unreviewed:
        st.write(", ".join(unreviewed))
    else:
        st.write("Every show in this view has at least one review — or no shows loaded yet.")

    st.divider()

    # ── All reviews found ───────────────────────────────────────────────
    st.subheader("Reviews found")
    if filtered_reviews:
        df = pd.DataFrame(filtered_reviews).sort_values("date_found", ascending=False)
        cols = [c for c in ["show_title", "venue", "review_source", "stars", "snippet", "url", "date_found"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True)
    else:
        st.write("No reviews found yet for this view. Check back once the tracker has run a few times.")


if __name__ == "__main__":
    show_dashboard()
