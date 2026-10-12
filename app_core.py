"""Server logic for the live news app. Used by the Vercel functions in api/ and by dev_server.py."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import news_core
from news_core import Article, app_feeds, collect_articles, publisher_article_details
from text_utils import clean_text

CACHE_SECONDS = 45  # how long one fetch is shared by every visitor on the same server instance
FORCE_MIN_INTERVAL = 20  # the refresh button cannot re-fetch every publisher more often than this
CDN_MAX_AGE = 30  # edge cache; stale copies are served instantly while a fresh one is fetched
CDN_STALE_WHILE_REVALIDATE = 120
FETCH_DEADLINE_SECONDS = 20  # slow sources are dropped after this so the rest still update
FETCH_TIMEOUT_SECONDS = 6
MAX_ITEMS = 300
SUMMARY_CHARS = 280

# Per-visitor limits: (requests, seconds). They are kept per server instance, so they stop a single
# client hammering the site but are not a global quota.
LIMITS = {"news": (120, 60), "refresh": (6, 60), "enrich": (90, 60)}

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "payload": None}
_known_links: set[str] = set()


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class RateLimiter:
    """Sliding-window limiter keyed by (bucket, client)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, client: str, now: float | None = None) -> None:
        limit, window = LIMITS[bucket]
        now = time.time() if now is None else now
        with self._lock:
            hits = self._hits[(bucket, client)]
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                raise RateLimited(max(1, int(window - (now - hits[0]))))
            hits.append(now)
            if len(self._hits) > 5000:  # forget idle clients so memory stays bounded
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= window]:
                    del self._hits[key]


limiter = RateLimiter()


def client_ip(headers, fallback: str = "unknown") -> str:
    forwarded = (headers.get("x-forwarded-for") or headers.get("x-real-ip") or "").split(",")[0].strip()
    return forwarded or fallback


# ------------------------------------------------------------------ safe outbound fetching


def is_public_host(host: str) -> bool:
    """True only when every address the host resolves to is a public internet address."""
    if not host:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    try:
        return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)
    except ValueError:
        return False


def check_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.port not in {None, 80, 443}:
        raise requests.exceptions.InvalidURL(f"blocked url: {url}")
    if not is_public_host(parsed.hostname or ""):
        raise requests.exceptions.InvalidURL(f"blocked non-public host: {parsed.hostname}")


class SafeSession(requests.Session):
    """A session that refuses private, loopback and link-local targets, including on every redirect hop."""

    def send(self, request, **kwargs):  # noqa: ANN001 - signature follows requests
        check_public_url(request.url)
        return super().send(request, **kwargs)


# ------------------------------------------------------------------ news payload


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
        "also": [{"source": name, "link": link, "title": title} for name, link, title in article.also],
    }


def fresh_payload() -> dict:
    started = time.time()
    stats: dict = {}
    articles = collect_articles(
        feeds=app_feeds(),
        workers=64,
        timeout=FETCH_TIMEOUT_SECONDS,
        retries=1,
        deadline=FETCH_DEADLINE_SECONDS,
        stats=stats,
    )
    # Newest first; the client re-sorts for "top stories".
    articles.sort(key=lambda a: a.published_at.timestamp() if a.published_at else 0, reverse=True)
    items = [serialize(article) for article in articles[:MAX_ITEMS]]
    # Only links we served may be enriched later, so /api/enrich can never act as an open proxy.
    _known_links.clear()
    _known_links.update(item["link"] for item in items if item["link"])
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "took_seconds": round(time.time() - started, 1),
        "count": len(items),
        "health": {"ok": stats.get("ok", 0), "total": stats.get("total", 0), "failed": stats.get("failed", [])},
        "items": items,
    }


def news_payload(force: bool = False) -> dict:
    """Return the cached payload, refetching all sources together when it is older than CACHE_SECONDS.

    The lock makes simultaneous visitors share one fetch instead of each hammering every publisher."""
    with _lock:
        age = time.time() - _cache["at"]
        if force and age < FORCE_MIN_INTERVAL:
            force = False
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
    if url not in _known_links:
        news_payload()  # a cold server instance may not have built its link list yet
        if url not in _known_links:
            raise PermissionError("unknown article link")
    article = Article(
        title="", source="", feed_label="", category="", score=0, published_at=None, link=url, summary=""
    )
    with SafeSession() as session:
        publisher_url, image_url, brief = publisher_article_details(session, article)
    return {"url": publisher_url, "image": image_url, "summary": clean_text(brief)[:SUMMARY_CHARS]}


def json_body(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def send_json(handler, status: int, data: dict, cache: str, extra: dict | None = None) -> None:
    """Write a JSON response on any BaseHTTPRequestHandler (Vercel's or the local dev server's)."""
    body = json_body(data)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", cache)
    for key, value in (extra or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)
