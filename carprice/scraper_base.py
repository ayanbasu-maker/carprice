from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod

import requests

from carprice.config import get_headers, get_delay, DEFAULT_TIMEOUT, MAX_RETRIES, PROXY_URL
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)


class ScraperBase(ABC):
    """Abstract base class for all car listing scrapers."""

    name: str = "base"
    requires_browser: bool = False

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(get_headers())
        if PROXY_URL:
            self.session.proxies = {"http": PROXY_URL, "https": PROXY_URL}

    @abstractmethod
    def search(self, params: SearchParams) -> list[Listing]:
        """Search for listings matching the given parameters."""
        ...

    def _get(self, url: str, **kwargs) -> requests.Response:
        """Make a GET request with retry logic and delays."""
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

        for attempt in range(MAX_RETRIES):
            try:
                # Rotate user-agent each request
                self.session.headers.update(get_headers())
                resp = self.session.get(url, **kwargs)

                if resp.status_code == 429:
                    wait = (attempt + 1) * get_delay(self.name) * 2
                    logger.warning(f"[{self.name}] Rate limited, waiting {wait:.1f}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp

            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    wait = (attempt + 1) * get_delay(self.name)
                    logger.warning(f"[{self.name}] Request failed ({e}), retrying in {wait:.1f}s")
                    time.sleep(wait)
                else:
                    raise

        raise requests.RequestException(f"[{self.name}] Max retries exceeded for {url}")

    def _delay(self):
        """Sleep for a source-appropriate random delay."""
        time.sleep(get_delay(self.name))
