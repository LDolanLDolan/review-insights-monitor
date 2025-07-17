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