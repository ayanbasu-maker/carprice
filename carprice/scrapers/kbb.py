from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

from carprice.scraper_base import ScraperBase
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)


class KBBScraper(ScraperBase):
    """
    KBB scraper for vehicle valuations.
    Returns valuation data (Fair Purchase Price, Trade-In, Private Party)
    rather than individual listings.
    """
    name = "kbb"
    requires_browser = True

    def search(self, params: SearchParams) -> list[Listing]:
        """
        KBB doesn't return listings in the traditional sense.
        Instead, we create a single "listing" entry representing the KBB valuation.
        The actual KBB values are stored and used by the analyzer.
        """
        valuation = self.get_valuation(params)
        if not valuation:
            return []

        # Return a synthetic listing so KBB data appears in the output
        fair = valuation.get("fair", 0)
        if fair:
            return [Listing(
                source="kbb",
                title=f"KBB Fair Purchase Price - {params.year} {params.make} {params.model}",
                price=fair,
                mileage=params.mileage,
                trim=params.trim,
                location="N/A (valuation)",
                dealer_name="Kelley Blue Book",
                is_dealer=True,
                url=f"https://www.kbb.com/{quote(params.make_lower)}/{quote(params.model_lower)}/{params.year}/",
            )]
        return []

    def get_valuation(self, params: SearchParams) -> dict | None:
        """Get KBB valuation for the vehicle. Returns dict with fair, trade_in, private_party keys."""

        # Try requests first to get any embedded pricing data
        url = f"https://www.kbb.com/{quote(params.make_lower)}/{quote(params.model_lower)}/{params.year}/"

        try:
            resp = self._get(url)
            valuation = self._extract_valuation_from_html(resp.text)
            if valuation:
                return valuation
        except Exception as e:
            logger.debug(f"[kbb] Requests approach failed: {e}")

        # Try with browser for JS-rendered content
        try:
            from carprice.browser import create_driver
            driver = create_driver()
            try:
                driver.get(url)
                self._delay()

                # Try to navigate the valuation flow
                html = driver.page_source
                valuation = self._extract_valuation_from_html(html)
                if valuation:
                    return valuation

                # Try entering mileage if there's an input
                try:
                    from selenium.webdriver.common.by import By
                    mileage_input = driver.find_elements(By.CSS_SELECTOR, "input[name*='mileage'], input[placeholder*='mileage']")
                    if mileage_input:
                        mileage_input[0].clear()
                        mileage_input[0].send_keys(str(params.mileage))
                        self._delay()
                        html = driver.page_source
                        valuation = self._extract_valuation_from_html(html)
                        if valuation:
                            return valuation
                except Exception:
                    pass

            finally:
                driver.quit()
        except Exception as e:
            logger.warning(f"[kbb] Browser approach failed: {e}")

        return None

    def _extract_valuation_from_html(self, html: str) -> dict | None:
        """Extract pricing data from KBB HTML."""
        valuation = {}

        # Look for embedded JSON with pricing data
        json_patterns = [
            r'"fairPurchasePrice"\s*:\s*([\d.]+)',
            r'"privateparty"\s*:\s*\{[^}]*"price"\s*:\s*([\d.]+)',
            r'"tradein"\s*:\s*\{[^}]*"price"\s*:\s*([\d.]+)',
        ]

        # Fair purchase price
        match = re.search(r'"fairPurchasePrice"\s*:\s*([\d,.]+)', html)
        if match:
            valuation["fair"] = int(float(match.group(1).replace(",", "")))

        match = re.search(r'"privateparty"[^}]*"price"\s*:\s*([\d,.]+)', html, re.DOTALL)
        if not match:
            match = re.search(r'Private\s*Party.*?\$([\d,]+)', html, re.DOTALL | re.IGNORECASE)
        if match:
            valuation["private_party"] = int(float(match.group(1).replace(",", "")))

        match = re.search(r'"tradein"[^}]*"price"\s*:\s*([\d,.]+)', html, re.DOTALL)
        if not match:
            match = re.search(r'Trade.?In.*?\$([\d,]+)', html, re.DOTALL | re.IGNORECASE)
        if match:
            valuation["trade_in"] = int(float(match.group(1).replace(",", "")))

        # Also look for general price values on the page
        if not valuation:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

            # Look for pricing sections
            price_sections = soup.find_all(string=re.compile(r'\$[\d,]+'))
            prices_found = []
            for section in price_sections:
                match = re.search(r'\$([\d,]+)', section)
                if match:
                    val = int(match.group(1).replace(",", ""))
                    if 1000 < val < 200000:
                        prices_found.append(val)

            if prices_found:
                prices_found.sort()
                if len(prices_found) >= 3:
                    valuation["trade_in"] = prices_found[0]
                    valuation["private_party"] = prices_found[len(prices_found) // 2]
                    valuation["fair"] = prices_found[-1]
                elif len(prices_found) >= 1:
                    valuation["fair"] = prices_found[0]

        return valuation if valuation else None
