import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from utils import analyze_sentiment, extract_quotes, plot_sentiment_chart, extract_review_content

st.set_page_config(
    page_title='Review Insights Monitor',
    page_icon='🧠',
    layout='wide',
    initial_sidebar_state='expanded'
)

st.title('🧠 Review Insights Monitor')
st.markdown('**Discover the positive highlights in any review.** Paste text, upload a file, or enter a webpage URL.')

# Sidebar for settings
with st.sidebar:
    st.header("⚙️ Settings")
    min_quote_length = st.slider("Minimum quote length", 30, 100, 50)
    quote_count = st.slider("Number of quotes to show", 1, 10, 3)

# Main input section
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

# Analysis section
if text and len(text.strip()) > 10:
    st.markdown("---")
    st.markdown("## 📊 Analysis Results")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Best quotes section
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
        # Sentiment summary
        st.markdown("### 📈 Sentiment Overview")
        sentiment = analyze_sentiment(text)
        
        # Sentiment metrics
        st.metric("Overall Polarity", f"{sentiment['polarity']:.3f}", 
                 help="Range: -1 (negative) to +1 (positive)")
        st.metric("Subjectivity", f"{sentiment['subjectivity']:.3f}",
                 help="Range: 0 (objective) to +1 (subjective)")
        
        # Sentiment interpretation
        polarity = sentiment['polarity']
        if polarity > 0.3:
            st.success("😊 Positive sentiment")
        elif polarity > 0:
            st.info("😐 Slightly positive")
        elif polarity > -0.3:
            st.warning("😕 Neutral to negative")
        else:
            st.error("😞 Negative sentiment")
    
    # Chart section
    st.markdown("### 📊 Sentiment Distribution")
    chart = plot_sentiment_chart(text)
    st.pyplot(chart)
    
    # Word count info
    word_count = len(text.split())
    st.info(f"📝 Analyzed {word_count} words")

else:
    st.info("👆 Please enter some text to analyze using one of the methods above.")

# Footer
st.markdown("---")
st.markdown("Built with ❤️ using Streamlit • Find positive insights in any review")