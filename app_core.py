"""Server logic for the live news app. Used by the Vercel functions in api/ and by dev_server.py."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import news_core
from news_core import Article, app_feeds, collect_articles, publisher_article_details
from text_utils import clean_text

CACHE_SECONDS = 45  # how long one fetch is shared by every visitor on the same server instance
CDN_MAX_AGE = 30  # edge cache; stale copies are served instantly while a fresh one is fetched
CDN_STALE_WHILE_REVALIDATE = 120
FETCH_DEADLINE_SECONDS = 20  # slow sources are dropped after this so the rest still update
FETCH_TIMEOUT_SECONDS = 6
MAX_ITEMS = 300
SUMMARY_CHARS = 280

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "payload": None}


def article_id(article: Article) -> str:
    key = news_core.normalize_for_dedupe(article.title)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def serialize(article: Article) -> dict:
    summary = news_core.trim_brief(news_core.text_from_html(article.summary), max_chars=SUMMARY_CHARS)
    if news_core.brief_is_weak(summary, article.title):
        summary = ""
    return {
        "id": article_id(article),
        "title": article.title,
        "source": article.source or article.feed_label,
        "category": article.category,
        "topics": list(article.topics),
        "region": article.region,
        "uae": article.uae_mention,
        "score": article.score,
        "published": article.published_at.astimezone(timezone.utc).isoformat() if article.published_at else None,
        "link": article.link,
        "image": article.image,
        "summary": summary,
    }


def fresh_payload() -> dict:
    started = time.time()
    articles = collect_articles(
        feeds=app_feeds(),
        workers=64,
        timeout=FETCH_TIMEOUT_SECONDS,
        retries=1,
        deadline=FETCH_DEADLINE_SECONDS,
    )
    # Newest first; the client re-sorts for "top stories".
    articles.sort(key=lambda a: a.published_at.timestamp() if a.published_at else 0, reverse=True)
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "took_seconds": round(time.time() - started, 1),
        "count": min(len(articles), MAX_ITEMS),
        "items": [serialize(article) for article in articles[:MAX_ITEMS]],
    }


def news_payload(force: bool = False) -> dict:
    """Return the cached payload, refetching all sources together when it is older than CACHE_SECONDS.

    The lock makes simultaneous visitors share one fetch instead of each hammering every publisher."""
    with _lock:
        age = time.time() - _cache["at"]
        if force and age < 5:
            force = False  # refresh button spam must not re-fetch every feed each time
        if _cache["payload"] is None or force or age > CACHE_SECONDS:
            try:
                _cache["payload"] = fresh_payload()
                _cache["at"] = time.time()
            except RuntimeError:
                if _cache["payload"] is None:
                    raise  # nothing to fall back on
        return _cache["payload"]


def enrich_payload(url: str) -> dict:
    """Find the real publisher URL, lead image and a short summary for one article (loaded lazily by the page)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid url")
    article = Article(
        title="", source="", feed_label="", category="", score=0, published_at=None, link=url, summary=""
    )
    with requests.Session() as session:
        publisher_url, image_url, brief = publisher_article_details(session, article)
    return {"url": publisher_url, "image": image_url, "summary": clean_text(brief)[:SUMMARY_CHARS]}


def json_body(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
