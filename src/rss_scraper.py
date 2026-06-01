"""
rss_scraper.py — Scrape Korean news via RSS feeds for .sillok daily records.

Fetches from major Korean news RSS feeds, categorizes articles
into .sillok sections, and outputs a sections JSON file.
"""

import json
import re
import sys
import os
import xml.etree.ElementTree as ET
from datetime import date, datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from html import unescape


# ============================================================
# RSS Feed sources mapped to .sillok sections
# ============================================================

FEEDS = {
    '정치': [
        'https://www.khan.co.kr/rss/rssdata/total_news.xml',  # 경향신문
        'https://www.hani.co.kr/rss/politics/',  # 한겨레
    ],
    '경제': [
        'https://www.khan.co.kr/rss/rssdata/economy_news.xml',
        'https://www.hani.co.kr/rss/economy/',
    ],
    '사회': [
        'https://www.khan.co.kr/rss/rssdata/society_news.xml',
        'https://www.hani.co.kr/rss/society/',
    ],
    '국제정세': [
        'https://www.khan.co.kr/rss/rssdata/world_news.xml',
        'https://www.hani.co.kr/rss/international/',
    ],
    '과학기술': [
        'https://www.khan.co.kr/rss/rssdata/it_news.xml',
        'https://www.hani.co.kr/rss/science/',
    ],
    '문화': [
        'https://www.khan.co.kr/rss/rssdata/culture_news.xml',
        'https://www.hani.co.kr/rss/culture/',
    ],
    '천재지변': [
        # Weather/disaster news — use general feeds and filter
        'https://www.khan.co.kr/rss/rssdata/society_news.xml',
    ],
}

# Keywords to filter weather/disaster articles
WEATHER_KEYWORDS = ['날씨', '기상', '태풍', '지진', '홍수', '폭우', '폭설',
                    '산불', '화재', '미세먼지', '황사', '한파', '폭염', '가뭄']


def fetch_rss(url, timeout=10):
    """Fetch and parse an RSS feed. Returns list of (title, description, pubdate)."""
    articles = []
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0 SillokBot/1.0'})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        root = ET.fromstring(data)

        for item in root.iter('item'):
            title = item.findtext('title', '').strip()
            desc = item.findtext('description', '').strip()
            pub_date = item.findtext('pubDate', '').strip()

            # Clean HTML from description
            desc = clean_html(desc)
            title = clean_html(title)

            if title:
                articles.append({
                    'title': title,
                    'description': desc,
                    'pubdate': pub_date,
                })
    except Exception as e:
        print(f"  Warning: Failed to fetch {url}: {e}", file=sys.stderr)

    return articles


def clean_html(text):
    """Remove HTML tags and decode entities."""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_today(pubdate_str, target_date=None):
    """Check if a pubdate string matches today (or target_date)."""
    if target_date is None:
        target_date = date.today()

    # Try common RSS date formats
    for fmt in ['%a, %d %b %Y %H:%M:%S %z',
                '%a, %d %b %Y %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S']:
        try:
            parsed = datetime.strptime(pubdate_str.strip(), fmt)
            return parsed.date() == target_date
        except ValueError:
            continue
    return True  # If we can't parse the date, include it


def is_weather_article(title, desc):
    """Check if article is about weather/disasters."""
    text = (title + ' ' + desc).lower()
    return any(kw in text for kw in WEATHER_KEYWORDS)


def scrape_section(section_name, feed_urls, target_date=None, max_articles=5):
    """Scrape articles for a section from its RSS feeds."""
    all_articles = []

    for url in feed_urls:
        articles = fetch_rss(url)
        for article in articles:
            if is_today(article['pubdate'], target_date):
                all_articles.append(article)

    # Deduplicate by title similarity
    seen_titles = set()
    unique = []
    for article in all_articles:
        # Simple dedup: first 20 chars of title
        key = article['title'][:20]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(article)

    # For weather section, filter by keywords
    if section_name == '천재지변':
        unique = [a for a in unique if is_weather_article(a['title'], a['description'])]

    # Take top N articles
    unique = unique[:max_articles]

    # Combine into section text
    lines = []
    for article in unique:
        # Use title + description as the article text
        text = article['title']
        if article['description'] and article['description'] != article['title']:
            text += '. ' + article['description']
        # Clean up
        text = text.replace('\n', ' ').strip()
        if text and not text.endswith('.'):
            text += '.'
        lines.append(text)

    return '\n'.join(lines)


def scrape_all_sections(target_date=None):
    """Scrape all sections and return a dict."""
    if target_date is None:
        target_date = date.today()

    print(f"Scraping news for {target_date.isoformat()}...")

    sections = {}
    for section_name, feed_urls in FEEDS.items():
        print(f"  {section_name}...", end=' ')
        content = scrape_section(section_name, feed_urls, target_date)
        sections[section_name] = content
        article_count = len(content.split('\n')) if content else 0
        print(f"{article_count} articles, {len(content)} chars")

    # 사신왈 is always empty (user fills in manually)
    sections['사신왈'] = ''

    return sections


def save_sections(sections, output_dir='.', target_date=None):
    """Save sections to a JSON file."""
    if target_date is None:
        target_date = date.today()

    filename = f"sections_{target_date.isoformat()}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(sections, f, ensure_ascii=False, indent=2)

    print(f"Saved to {filepath}")
    return filepath


if __name__ == '__main__':
    # Parse optional date argument
    target = None
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])

    sections = scrape_all_sections(target)
    save_sections(sections, target_date=target)
