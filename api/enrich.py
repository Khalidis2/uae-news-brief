"""GET /api/enrich?u=<article url> - real publisher link, lead image and summary for one story."""

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_core  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        try:
            body = app_core.json_body(app_core.enrich_payload(query.get("u", [""])[0]))
            status, cache = 200, "public, s-maxage=86400, stale-while-revalidate=604800"
        except ValueError as exc:
            body, status, cache = app_core.json_body({"error": str(exc)}), 400, "no-store"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)
