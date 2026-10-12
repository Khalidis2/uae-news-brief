import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app_core  # noqa: E402
import news_core  # noqa: E402

PUBLIC_IP = "93.184.216.34"


def fake_resolver(mapping):
    def getaddrinfo(host, *_args, **_kwargs):
        if host in mapping:
            return [(2, 1, 6, "", (mapping[host], 0))]
        import socket
        try:
            import ipaddress
            ipaddress.ip_address(host)
            return [(2, 1, 6, "", (host, 0))]
        except ValueError:
            raise socket.gaierror("no such host")
    return getaddrinfo


class RedirectAdapter(requests.adapters.BaseAdapter):
    """Serves a fixed redirect for one URL and a 200 for everything else; records what was requested."""

    def __init__(self, redirects):
        super().__init__()
        self.redirects, self.requested = redirects, []

    def send(self, request, **kwargs):
        self.requested.append(request.url)
        response = requests.Response()
        response.request, response.url = request, request.url
        if request.url in self.redirects:
            response.status_code = 302
            response.headers["Location"] = self.redirects[request.url]
        else:
            response.status_code, response._content = 200, b"ok"
        return response

    def close(self):
        pass


class OutboundSafety(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("socket.getaddrinfo", fake_resolver({"good.example": PUBLIC_IP, "internal.example": "10.1.2.3", "local.example": "127.0.0.1"}))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_private_and_special_addresses_are_not_public(self):
        for host in ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1", "172.16.0.9", "169.254.169.254", "0.0.0.0", "::1", "internal.example", "local.example", "", "nonexistent.example"]:
            with self.subTest(host=host):
                self.assertFalse(app_core.is_public_host(host))

    def test_public_address_is_allowed(self):
        self.assertTrue(app_core.is_public_host("good.example"))
        self.assertTrue(app_core.is_public_host("8.8.8.8"))

    def test_session_refuses_private_targets_and_odd_schemes_and_ports(self):
        session = app_core.SafeSession()
        adapter = RedirectAdapter({})
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        for url in ["http://169.254.169.254/latest/meta-data/", "http://internal.example/", "http://127.0.0.1:8000/", "http://good.example:8080/", "file:///etc/passwd", "ftp://good.example/x"]:
            with self.subTest(url=url):
                with self.assertRaises(requests.exceptions.RequestException):
                    session.get(url)
        self.assertEqual(adapter.requested, [], "nothing blocked may reach the network")

    def test_session_allows_public_urls(self):
        session = app_core.SafeSession()
        session.mount("https://", RedirectAdapter({}))
        self.assertEqual(session.get("https://good.example/story").status_code, 200)

    def test_redirect_into_private_network_is_blocked(self):
        session = app_core.SafeSession()
        adapter = RedirectAdapter({"https://good.example/a": "http://169.254.169.254/latest/meta-data/"})
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        with self.assertRaises(requests.exceptions.RequestException):
            session.get("https://good.example/a")
        self.assertEqual(adapter.requested, ["https://good.example/a"])


class EnrichEndpoint(unittest.TestCase):
    def setUp(self):
        app_core._known_links.clear()

    def test_unknown_link_is_rejected(self):
        with mock.patch.object(app_core, "news_payload", return_value={}), \
             mock.patch.object(app_core, "publisher_article_details") as fetch:
            with self.assertRaises(PermissionError):
                app_core.enrich_payload("https://evil.example/anything")
            fetch.assert_not_called()

    def test_non_http_is_rejected(self):
        for url in ["file:///etc/passwd", "javascript:alert(1)", "gopher://x", ""]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    app_core.enrich_payload(url)

    def test_served_link_is_enriched(self):
        app_core._known_links.add("https://news.example/story")
        with mock.patch.object(app_core, "publisher_article_details", return_value=("https://news.example/story", "https://img/x.jpg", "A summary.")):
            result = app_core.enrich_payload("https://news.example/story")
        self.assertEqual(result["image"], "https://img/x.jpg")

    def test_cold_instance_rebuilds_link_list_once(self):
        def populate():
            app_core._known_links.add("https://news.example/story")
            return {}
        with mock.patch.object(app_core, "news_payload", side_effect=populate) as build, \
             mock.patch.object(app_core, "publisher_article_details", return_value=("u", "", "")):
            app_core.enrich_payload("https://news.example/story")
        build.assert_called_once()


class Limits(unittest.TestCase):
    def test_blocks_after_limit_then_recovers(self):
        limiter = app_core.RateLimiter()
        with mock.patch.dict(app_core.LIMITS, {"refresh": (3, 60)}):
            for n in range(3):
                limiter.check("refresh", "1.2.3.4", now=100 + n)
            with self.assertRaises(app_core.RateLimited) as caught:
                limiter.check("refresh", "1.2.3.4", now=110)
            self.assertGreaterEqual(caught.exception.retry_after, 1)
            limiter.check("refresh", "5.6.7.8", now=110)   # other clients are unaffected
            limiter.check("refresh", "1.2.3.4", now=170)   # window passed
            limiter.check("news", "1.2.3.4", now=110)      # other buckets are independent

    def test_client_ip_prefers_forwarded_header(self):
        self.assertEqual(app_core.client_ip({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, "127.0.0.1"), "9.9.9.9")
        self.assertEqual(app_core.client_ip({}, "127.0.0.1"), "127.0.0.1")

    def test_forced_refresh_cannot_refetch_inside_min_interval(self):
        app_core._cache.update(at=app_core.time.time(), payload={"count": 1})
        with mock.patch.object(app_core, "fresh_payload") as fetch:
            self.assertEqual(app_core.news_payload(force=True), {"count": 1})
            fetch.assert_not_called()


class SourceHealth(unittest.TestCase):
    def test_stats_report_working_and_failed_sources(self):
        feeds = [news_core.RssFeed("A", "u1", 5), news_core.RssFeed("B", "u2", 5), news_core.RssFeed("C", "u3", 5)]
        with mock.patch.object(news_core, "fetch_all_feeds", return_value=[(feeds[0], []), (feeds[1], None), (feeds[2], [])]):
            stats = {}
            news_core.collect_articles(feeds=feeds, stats=stats)
        self.assertEqual((stats["ok"], stats["total"], stats["failed"]), (2, 3, ["B"]))

    def test_all_sources_failing_raises(self):
        feeds = [news_core.RssFeed("A", "u1", 5)]
        with mock.patch.object(news_core, "fetch_all_feeds", return_value=[(feeds[0], None)]):
            with self.assertRaises(RuntimeError):
                news_core.collect_articles(feeds=feeds)


if __name__ == "__main__":
    unittest.main()
