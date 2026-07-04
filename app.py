import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import json
from pathlib import Path
import pandas as pd
from utils import analyze_sentiment, extract_quotes, plot_sentiment_chart, extract_review_content

st.set_page_config(
    page_title='Review Insights Monitor',
    page_icon='🧠',
    layout='wide',
    initial_sidebar_state='expanded'
)

DATA_DIR = Path(__file__).parent / "data"


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


tab1, tab2 = st.tabs(["🧠 Sentiment Analyser", "🎭 C Venues Review Tracker"])

# ══════════════════════════════════════════════════════════════════════════
# TAB 1 — original sentiment analysis tool, unchanged
# ══════════════════════════════════════════════════════════════════════════
with tab1:
    st.title('🧠 Review Insights Monitor')
    st.markdown('**Discover the positive highlights in any review.** Paste text, upload a file, or enter a webpage URL.')

    with st.sidebar:
        st.header("⚙️ Settings")
        min_quote_length = st.slider("Minimum quote length", 30, 100, 50)
        quote_count = st.slider("Number of quotes to show", 1, 10, 3)

    option = st.radio("Choose input method:", ("📝 Paste Text", "🔗 Enter URL", "📁 Upload File"))

    text = ''
    if option == "📝 Paste Text":
        text = st.text_area("Paste your review or feedback text here:", height=150)

    elif option == "🔗 Enter URL":
        url = st.text_input("Enter URL (TripAdvisor, Yelp, Amazon, etc.):")
        if url and st.button("Fetch Reviews"):
            with st.spinner("Fetching content..."):
                try:
                    text = extract_review_content(url)
                    if text:
                        st.success("Content extracted successfully!")
                        st.text_area("Extracted text:", text[:500] + "..." if len(text) > 500 else text, height=100)
                    else:
                        st.error("No content could be extracted from this URL.")
                except Exception as e:
                    st.error(f"Error fetching content: {str(e)}")

    elif option == "📁 Upload File":
        uploaded = st.file_uploader("Upload a text file:", type=['txt'])
        if uploaded:
            text = uploaded.read().decode("utf-8")
            st.success(f"File uploaded: {uploaded.name}")

    if text and len(text.strip()) > 10:
        st.markdown("---")
        st.markdown("## 📊 Analysis Results")

        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown("### ✨ Top Positive Highlights")
            quotes = extract_quotes(text, min_length=min_quote_length, count=quote_count)

            if quotes:
                for i, quote in enumerate(quotes, 1):
                    sentiment_score = analyze_sentiment(quote)['polarity']
                    st.markdown(f"""
                    <div style="background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin: 10px 0; border-left: 4px solid #4CAF50;">
                        <strong>Quote {i}</strong> (Sentiment: {sentiment_score:.2f})
                        <br>💬 "{quote}"
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.warning("No positive quotes found. Try adjusting the minimum quote length in the sidebar.")

        with col2:
            st.markdown("### 📈 Sentiment Overview")
            sentiment = analyze_sentiment(text)

            st.metric("Overall Polarity", f"{sentiment['polarity']:.3f}",
                     help="Range: -1 (negative) to +1 (positive)")
            st.metric("Subjectivity", f"{sentiment['subjectivity']:.3f}",
                     help="Range: 0 (objective) to +1 (subjective)")

            polarity = sentiment['polarity']
            if polarity > 0.3:
                st.success("😊 Positive sentiment")
            elif polarity > 0:
                st.info("😐 Slightly positive")
            elif polarity > -0.3:
                st.warning("😕 Neutral to negative")
            else:
                st.error("😞 Negative sentiment")

        st.markdown("### 📊 Sentiment Distribution")
        chart = plot_sentiment_chart(text)
        st.pyplot(chart)

        word_count = len(text.split())
        st.info(f"📝 Analyzed {word_count} words")

    else:
        st.info("👆 Please enter some text to analyze using one of the methods above.")

    st.markdown("---")
    st.markdown("Built with ❤️ using Streamlit • Find positive insights in any review")

# ══════════════════════════════════════════════════════════════════════════
# TAB 2 — C Venues Review Tracker dashboard (reads data files GitHub Actions updates)
# ══════════════════════════════════════════════════════════════════════════
with tab2:
    st.title("🎭 C Venues Review Tracker")
    st.markdown("Automatically checks Broadway Baby, FringeReview, ThreeWeeks and 30+ other sites twice a day.")

    status = load_json(DATA_DIR / "status.json", {})
    reviews = load_json(DATA_DIR / "reviews.json", [])
    shows = load_json(DATA_DIR / "shows.json", [])

    col1, col2, col3 = st.columns(3)
    last_run = status.get("last_run") or "never"
    col1.metric("Last checked", last_run[:16].replace("T", " ") if last_run != "never" else "never")
    col2.metric("Shows checked today", status.get("shows_in_todays_batch", 0))
    col3.metric("Reviews found so far", status.get("total_reviews_tracked", 0))

    total = status.get("total_shows", 0)
    if total:
        st.caption(
            f"Rotates through all {total} shows in batches — full list re-checked every few days, "
            f"not all of them every single run, to stay within the free search quota."
        )

    if status.get("status") not in ("ok", None):
        st.warning(f"Status: {status.get('status')}")

    st.divider()

    venues = sorted({s.get("venue", "") for s in shows if s.get("venue")})
    selected_venue = st.selectbox("Filter by venue", ["All venues"] + venues)

    if selected_venue == "All venues":
        filtered_shows = shows
    else:
        filtered_shows = [s for s in shows if s.get("venue") == selected_venue]
    filtered_titles = {s["title"] for s in filtered_shows}
    filtered_reviews = [r for r in reviews if r["show_title"] in filtered_titles]

    st.divider()

    reviewed_titles = {r["show_title"] for r in filtered_reviews}
    unreviewed = sorted(filtered_titles - reviewed_titles)

    st.subheader(f"Shows with no reviews yet ({len(unreviewed)} of {len(filtered_titles)})")
    if unreviewed:
        st.write(", ".join(unreviewed))
    else:
        st.write("Every show in this view has at least one review — or no shows loaded yet.")

    st.divider()

    st.subheader("Reviews found")
    if filtered_reviews:
        df = pd.DataFrame(filtered_reviews).sort_values("date_found", ascending=False)
        cols = [c for c in ["show_title", "venue", "review_source", "stars", "snippet", "url", "date_found"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True)
    else:
        st.write("No reviews found yet for this view. Check back once the tracker has run a few times — "
                 "reviews typically start appearing from early August.")
