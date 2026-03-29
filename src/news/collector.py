"""News collection from free sources: RSS feeds, NewsAPI free tier, and web search."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx
import structlog
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.core.config import config

log = structlog.get_logger()

# Curated RSS feeds by category
RSS_FEEDS = {
    "crypto": [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed",
    ],
    "politics": [
        "https://rss.politico.com/politics-news.xml",
        "https://feeds.npr.org/1014/rss.xml",  # NPR Politics
        "https://www.reuters.com/rssFeed/politicsNews",
    ],
    "economics": [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://www.reuters.com/rssFeed/businessNews",
    ],
    "tech": [
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.theverge.com/rss/index.xml",
    ],
    "general": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    ],
}


def _parse_rss_xml(xml_text: str, feed_url: str) -> list[dict]:
    """Parse RSS/Atom XML using stdlib. Returns list of article dicts."""
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Detect Atom namespace
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    feed_title = feed_url

    # RSS 2.0: <channel><item>
    channel = root.find("channel")
    if channel is not None:
        ft = channel.find("title")
        if ft is not None and ft.text:
            feed_title = ft.text
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            content = re.sub(r"<[^>]+>", " ", desc).strip()
            articles.append({
                "source": feed_title,
                "title": title,
                "url": link,
                "content": content[:1000],
                "published": pub_date,
            })
    else:
        # Atom: <feed><entry>
        ft = root.find("atom:title", ns) or root.find("title")
        if ft is not None and ft.text:
            feed_title = ft.text
        for entry in root.findall("atom:entry", ns) or root.findall("entry"):
            title_el = entry.find("atom:title", ns) or entry.find("title")
            title = (title_el.text if title_el is not None else "").strip()
            link_el = entry.find("atom:link", ns) or entry.find("link")
            link = (link_el.get("href", "") if link_el is not None else "").strip()
            summary_el = entry.find("atom:summary", ns) or entry.find("summary") or entry.find("atom:content", ns) or entry.find("content")
            desc = (summary_el.text if summary_el is not None else "").strip()
            pub_el = entry.find("atom:published", ns) or entry.find("published") or entry.find("atom:updated", ns) or entry.find("updated")
            pub_date = (pub_el.text if pub_el is not None else "").strip()
            content = re.sub(r"<[^>]+>", " ", desc).strip()
            articles.append({
                "source": feed_title,
                "title": title,
                "url": link,
                "content": content[:1000],
                "published": pub_date,
            })

    return articles


async def fetch_rss_news(
    categories: Optional[list[str]] = None,
    max_age_hours: int = 24,
    max_per_feed: int = 10,
) -> list[dict]:
    """Fetch news from RSS feeds. Free, no API key needed."""
    if categories is None:
        categories = list(RSS_FEEDS.keys())

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    all_articles = []

    async with httpx.AsyncClient(timeout=15) as client:
        for category in categories:
            feeds = RSS_FEEDS.get(category, [])
            for feed_url in feeds:
                try:
                    resp = await client.get(feed_url, follow_redirects=True)
                    items = _parse_rss_xml(resp.text, feed_url)

                    for item in items[:max_per_feed]:
                        item["category"] = category
                        all_articles.append(item)
                except Exception as e:
                    log.warning("rss_fetch_failed", feed=feed_url, error=str(e))

    # Deduplicate by title similarity
    seen_titles = set()
    unique = []
    for article in all_articles:
        # Simple dedup: normalize title
        norm_title = article["title"].lower().strip()[:80]
        if norm_title not in seen_titles:
            seen_titles.add(norm_title)
            unique.append(article)

    log.info("rss_collected", total=len(unique), categories=categories)
    return unique


async def fetch_newsapi(
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """Fetch from NewsAPI free tier (100 requests/day)."""
    api_key = config.news.newsapi_key
    if not api_key:
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "sortBy": "publishedAt",
                "pageSize": max_results,
                "language": "en",
                "apiKey": api_key,
            },
        )
        if resp.status_code != 200:
            log.warning("newsapi_error", status=resp.status_code)
            return []
        data = resp.json()

    articles = []
    for a in data.get("articles", []):
        articles.append({
            "source": a.get("source", {}).get("name", "NewsAPI"),
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "content": (a.get("content", "") or a.get("description", ""))[:1000],
            "published": a.get("publishedAt", ""),
            "category": "newsapi",
        })
    log.info("newsapi_collected", query=query, count=len(articles))
    return articles


async def search_news_for_market(market: dict) -> list[dict]:
    """Collect relevant news for a specific market from all available sources."""
    question = market.get("question", "")
    category = market.get("category", "general")

    # Get category-specific RSS
    rss_news = await fetch_rss_news(
        categories=[category, "general"] if category != "general" else ["general"],
        max_age_hours=48,
    )

    # Filter RSS by relevance (simple keyword matching)
    keywords = _extract_keywords(question)
    relevant_rss = []
    for article in rss_news:
        text = (article["title"] + " " + article["content"]).lower()
        if any(kw in text for kw in keywords):
            article["relevance"] = "keyword_match"
            relevant_rss.append(article)

    # Try NewsAPI if we have a key
    newsapi_results = await fetch_newsapi(question[:100], max_results=5)

    combined = relevant_rss + newsapi_results

    # Sort by recency
    combined.sort(key=lambda x: x.get("published", ""), reverse=True)

    log.info(
        "news_for_market",
        market=question[:60],
        rss_relevant=len(relevant_rss),
        newsapi=len(newsapi_results),
    )
    return combined[:15]


def _extract_keywords(question: str) -> list[str]:
    """Extract meaningful keywords from a market question."""
    stop_words = {
        "will", "the", "be", "is", "a", "an", "in", "on", "at", "to", "for",
        "of", "by", "or", "and", "before", "after", "this", "that", "with",
        "from", "above", "below", "between", "does", "do", "has", "have",
        "more", "than", "yes", "no", "what", "when", "how", "who",
    }
    words = question.lower().split()
    keywords = [w.strip("?.,!") for w in words if w.strip("?.,!") not in stop_words and len(w) > 2]
    return keywords[:8]
