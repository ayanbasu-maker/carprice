"""Debug endpoint — returns raw HTML snippet from a target URL."""
from __future__ import annotations

import random
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        target = qs.get("url", ["https://austin.craigslist.org/search/cta?query=Porsche+911&min_auto_year=2011&max_auto_year=2011&sort=date&postal=78750&search_distance=100"])[0]

        session = requests.Session()
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
        })

        try:
            resp = session.get(target, timeout=15, allow_redirects=True)
            html = resp.text
            result = {
                "status": resp.status_code,
                "final_url": resp.url,
                "content_length": len(html),
                "html_snippet": html[:3000],
                "has_cl_search_result": "cl-search-result" in html,
                "has_priceinfo": "priceinfo" in html,
                "has_vehicle_card": "vehicle-card" in html,
                "has_captcha": "captcha" in html.lower() or "cf-browser-verification" in html.lower(),
                "has_cloudflare": "cloudflare" in html.lower() or "__cf_bm" in html.lower(),
                "response_headers": dict(resp.headers),
            }
        except Exception as e:
            result = {"error": str(e)}

        body = json.dumps(result, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
