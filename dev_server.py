"""Run the live app locally:  python dev_server.py  ->  http://localhost:8000

Serves public/ and the same /api/news and /api/enrich handlers that Vercel runs.
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import enrich  # noqa: E402
import news  # noqa: E402

API = {"/api/news": news.handler, "/api/enrich": enrich.handler}


class Dev(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in API:
            # Reuse the Vercel handler's logic against this connection.
            API[path].do_GET(self)
            return
        target = (ROOT / "public" / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not str(target).startswith(str(ROOT / "public")) or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Live news app on http://localhost:{args.port}")
    ThreadingHTTPServer(("", args.port), Dev).serve_forever()
