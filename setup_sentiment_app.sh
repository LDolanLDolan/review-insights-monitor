#!/bin/bash

# Navigate to your desired folder
cd ~/Desktop

# Clone your existing repo or create new folder
if [ -d "review-insights-monitor" ]; then
    echo "Directory exists, entering it..."
    cd review-insights-monitor
else
    echo "Cloning your existing repository..."
    git clone https://github.com/LDolanLDolan/review-insights-monitor.git
    cd review-insights-monitor
fi

# Create app.py
cat > app.py << 'EOF'
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
EOF

# Create utils.py
cat > utils.py << 'EOF'
from textblob import TextBlob
import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse
import time

def analyze_sentiment(text):
    """Analyze sentiment of given text using TextBlob."""
    if not text or len(text.strip()) == 0:
        return {'polarity': 0, 'subjectivity': 0}
    
    blob = TextBlob(text)
    return {
        'polarity': round(blob.sentiment.polarity, 3),
        'subjectivity': round(blob.sentiment.subjectivity, 3)
    }

def extract_quotes(text, min_length=50, count=3):
    """Extract the most positive quotes from text."""
    if not text:
        return []
    
    blob = TextBlob(text)
    sentences = blob.sentences
    
    # Filter sentences that are positive and meet minimum length
    good_quotes = []
    for sentence in sentences:
        sentence_str = str(sentence).strip()
        if (sentence.sentiment.polarity > 0.2 and 
            len(sentence_str) >= min_length and 
            len(sentence_str) <= 200):  # Max length to avoid very long sentences
            good_quotes.append(sentence_str)
    
    # Sort by sentiment polarity (most positive first)
    good_quotes.sort(key=lambda x: -TextBlob(x).sentiment.polarity)
    
    return good_quotes[:count]

def plot_sentiment_chart(text):
    """Create a pie chart showing sentiment distribution."""
    if not text:
        return None
    
    blob = TextBlob(text)
    counts = {"Positive": 0, "Neutral": 0, "Negative": 0}
    
    for sentence in blob.sentences:
        polarity = sentence.sentiment.polarity
        if polarity > 0.1:
            counts["Positive"] += 1
        elif polarity < -0.1:
            counts["Negative"] += 1
        else:
            counts["Neutral"] += 1
    
    # Create the plot
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = ['#4CAF50', '#FFC107', '#F44336']  # Green, Yellow, Red
    wedges, texts, autotexts = ax.pie(
        counts.values(), 
        labels=counts.keys(), 
        autopct='%1.1f%%', 
        startangle=140,
        colors=colors
    )
    
    ax.set_title('Sentiment Distribution by Sentence', fontsize=14, fontweight='bold')
    plt.tight_layout()
    return fig

def extract_review_content(url):
    """Extract review content from various review websites."""
    if not url:
        return ""
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Try different selectors based on common review sites
        domain = urlparse(url).netloc.lower()
        text = ""
        
        if 'tripadvisor' in domain:
            reviews = soup.find_all(['div'], class_=re.compile(r'review|Review'))
            text = ' '.join([r.get_text() for r in reviews])
        elif 'yelp' in domain:
            reviews = soup.find_all(['p', 'span'], class_=re.compile(r'comment|review'))
            text = ' '.join([r.get_text() for r in reviews])
        elif 'amazon' in domain:
            reviews = soup.find_all(['span'], {'data-hook': 'review-body'})
            text = ' '.join([r.get_text() for r in reviews])
        else:
            # Generic extraction
            text = soup.get_text()
        
        # Clean up the text
        text = re.sub(r'\s+', ' ', text)  # Replace multiple whitespace with single space
        text = text.strip()
        
        return text if len(text) > 50 else ""
        
    except Exception as e:
        raise Exception(f"Failed to extract content: {str(e)}")
EOF

# Create requirements.txt
cat > requirements.txt << 'EOF'
streamlit>=1.28.0
textblob>=0.17.1
matplotlib>=3.5.0
requests>=2.28.0
beautifulsoup4>=4.11.0
lxml>=4.9.0
EOF

# Create .streamlit/config.toml for better defaults
mkdir -p .streamlit
cat > .streamlit/config.toml << 'EOF'
[theme]
primaryColor = "#4CAF50"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"

[server]
headless = true
enableCORS = false
enableXsrfProtection = false
EOF

# Create README.md
cat > README.md << 'EOF'
# Review Insights Monitor 🧠

A Streamlit app that extracts positive highlights from reviews and feedback.

## Features

- 📝 **Text Analysis**: Paste any review text for instant analysis
- 🔗 **URL Extraction**: Automatically extract reviews from websites
- 📁 **File Upload**: Upload .txt files containing reviews
- ✨ **Positive Highlights**: Find the 3 most positive quotes
- 📊 **Sentiment Analysis**: Get detailed sentiment metrics
- 📈 **Visual Charts**: See sentiment distribution

## Installation

1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run the app: `streamlit run app.py`

## Supported Websites

- TripAdvisor
- Yelp
- Amazon Reviews
- Any website with review content

## Usage

1. Choose your input method (paste text, enter URL, or upload file)
2. The app will automatically extract positive highlights
3. View sentiment analysis and distribution charts
4. Adjust settings in the sidebar for customization

## Deploy to Streamlit Cloud

1. Push this repository to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repository
4. Deploy!
EOF

# Add GitHub Actions for automated deployment (optional)
mkdir -p .github/workflows
cat > .github/workflows/streamlit.yml << 'EOF'
name: Deploy to Streamlit Cloud

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Setup Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    - name: Test app
      run: |
        python -c "import streamlit; print('Streamlit installed successfully')"
EOF

# Create .gitignore
cat > .gitignore << 'EOF'
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/
.env
.DS_Store
*.log
.streamlit/secrets.toml
EOF

echo "✅ Files created successfully!"
echo ""
echo "📁 Created files:"
echo "- app.py (main Streamlit application)"
echo "- utils.py (utility functions)"
echo "- requirements.txt (dependencies)"
echo "- README.md (documentation)"
echo "- .streamlit/config.toml (Streamlit configuration)"
echo "- .github/workflows/streamlit.yml (GitHub Actions)"
echo "- .gitignore (Git ignore file)"
echo ""

# Git operations
echo "🔄 Setting up Git..."

# Add all files
git add .

# Commit changes
git commit -m "Enhanced sentiment analysis app with improved UI and functionality"

# Push to your existing repository
echo "📤 Pushing to GitHub..."
git push origin main

echo ""
echo "🎉 Successfully updated your repository!"
echo "🌐 Your repo: https://github.com/LDolanLDolan/review-insights-monitor"
echo ""
echo "🚀 Next steps:"
echo "1. Go to https://share.streamlit.io"
echo "2. Connect your GitHub account"
echo "3. Deploy from your repository"
echo "4. Your app will be live!"