"""GET /api/news - every current story as JSON. The page filters it locally, so filters are instant."""

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_core  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        force = "t" in query  # the refresh button adds ?t=<timestamp> to bypass the edge cache
        client = app_core.client_ip(self.headers, self.client_address[0])
        try:
            app_core.limiter.check("refresh" if force else "news", client)
            payload = app_core.news_payload(force=force)
        except app_core.RateLimited as exc:
            app_core.send_json(self, 429, {"error": "slow down"}, "no-store", {"Retry-After": str(exc.retry_after)})
            return
        except RuntimeError as exc:
            app_core.send_json(self, 503, {"error": str(exc)}, "no-store")
            return
        cache = "no-store" if force else f"public, s-maxage={app_core.CDN_MAX_AGE}, stale-while-revalidate={app_core.CDN_STALE_WHILE_REVALIDATE}"
        app_core.send_json(self, 200, payload, cache)
