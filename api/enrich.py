"""GET /api/enrich?u=<article url> - real publisher link, lead image and summary for one story.

Only links that /api/news served are accepted, and outbound requests to private addresses are blocked.
"""

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_core  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        client = app_core.client_ip(self.headers, self.client_address[0])
        try:
            app_core.limiter.check("enrich", client)
            data = app_core.enrich_payload(query.get("u", [""])[0])
        except app_core.RateLimited as exc:
            app_core.send_json(self, 429, {"error": "slow down"}, "no-store", {"Retry-After": str(exc.retry_after)})
        except ValueError as exc:
            app_core.send_json(self, 400, {"error": str(exc)}, "no-store")
        except PermissionError as exc:
            app_core.send_json(self, 403, {"error": str(exc)}, "no-store")
        except (requests.RequestException, RuntimeError):
            app_core.send_json(self, 502, {"error": "could not load the article"}, "no-store")
        else:
            app_core.send_json(self, 200, data, "public, s-maxage=86400, stale-while-revalidate=604800")
