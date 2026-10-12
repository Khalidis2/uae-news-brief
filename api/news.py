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
        try:
            body = app_core.json_body(app_core.news_payload(force=force))
            status = 200
            cache = (
                "no-store"
                if force
                else f"public, s-maxage={app_core.CDN_MAX_AGE}, stale-while-revalidate={app_core.CDN_STALE_WHILE_REVALIDATE}"
            )
        except RuntimeError as exc:
            body = app_core.json_body({"error": str(exc)})
            status, cache = 503, "no-store"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)
