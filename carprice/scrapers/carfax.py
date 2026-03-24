from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from carprice.scraper_base import ScraperBase
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)


class CarFaxScraper(ScraperBase):
    name = "carfax"
    requires_browser = True

    def search(self, params: SearchParams) -> list[Listing]:
        make = params.make_lower
        model = params.model_lower

        # CarFax used car listings URL
        make_cap = make.replace(" ", "-").title()
        model_cap = model.replace(" ", "-").title()
        url = (
            f"https://www.carfax.com/Used-{params.year}-{quote(make_cap)}-{quote(model_cap)}"
            f"_z{params.zip_code}"
        )

        # Try requests first
        try:
            resp = self._get(url)
            listings = self._parse_results(resp.text, params)
            if listings:
                return listings
        except Exception as e:
            logger.debug(f"[carfax] Requests failed: {e}")

        # Try browser
        try:
            from carprice.browser import create_driver
            driver = create_driver()
            try:
                driver.get(url)
                self._delay()
                html = driver.page_source
                listings = self._parse_results(html, params)
                return listings
            finally:
                driver.quit()
        except Exception as e:
            logger.warning(f"[carfax] Browser approach failed: {e}")

        return []

    def _parse_results(self, html: str, params: SearchParams) -> list[Listing]:
        """Parse CarFax search results."""
        listings = []

        # Try embedded JSON first
        listings = self._extract_json(html, params)
        if listings:
            return listings

        # Parse HTML
        soup = BeautifulSoup(html, "lxml")

        cards = (
            soup.select("[class*='listing-card']")
            or soup.select("[class*='srp-listing']")
            or soup.select("article")
        )

        for card in cards:
            try:
                # Title
                title_el = card.select_one("h2, h3, .vehicle-title, [class*='title']")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)

                # Price
                price_el = card.select_one("[class*='price'], .vehicle-price")
                if not price_el:
                    continue
                price = self._parse_price(price_el.get_text(strip=True))
                if not price:
                    continue

                # Mileage
                mileage = None
                mileage_el = card.find(string=re.compile(r'[\d,]+\s*(?:mi|miles)'))
                if mileage_el:
                    m = re.search(r'([\d,]+)\s*(?:mi|miles)', mileage_el)
                    if m:
                        mileage = int(m.group(1).replace(",", ""))

                # Link
                link_el = card.select_one("a[href*='vehicle']") or card.select_one("a[href]")
                url = ""
                if link_el:
                    href = link_el.get("href", "")
                    url = href if href.startswith("http") else f"https://www.carfax.com{href}"

                # Dealer
                dealer_el = card.select_one("[class*='dealer'], [class*='seller']")
                dealer = dealer_el.get_text(strip=True) if dealer_el else None

                # Location
                loc_el = card.select_one("[class*='location']")
                location = loc_el.get_text(strip=True) if loc_el else None

                # Trim
                trim = self._extract_trim(title, params)

                listings.append(Listing(
                    source="carfax",
                    title=title,
                    price=price,
                    mileage=mileage,
                    trim=trim,
                    location=location,
                    dealer_name=dealer,
                    is_dealer=True,
                    url=url,
                ))
            except Exception as e:
                logger.debug(f"[carfax] Failed to parse card: {e}")

        logger.info(f"[carfax] Found {len(listings)} listings")
        return listings

    def _extract_json(self, html: str, params: SearchParams) -> list[Listing]:
        """Try to extract listings from JSON-LD or embedded JSON."""
        listings = []

        # JSON-LD
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        scripts = soup.select('script[type="application/ld+json"]')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        listing = self._json_to_listing(item, params)
                        if listing:
                            listings.append(listing)
                elif isinstance(data, dict):
                    if data.get("@type") in ("Vehicle", "Car", "Product"):
                        listing = self._json_to_listing(data, params)
                        if listing:
                            listings.append(listing)
            except (json.JSONDecodeError, TypeError):
                continue

        return listings

    def _json_to_listing(self, data: dict, params: SearchParams) -> Listing | None:
        """Convert JSON-LD vehicle data to a Listing."""
        try:
            name = data.get("name", "")
            offers = data.get("offers", {})
            price = offers.get("price") if isinstance(offers, dict) else None
            if not price:
                return None
            price = int(float(str(price).replace(",", "")))

            mileage = data.get("mileageFromOdometer", {})
            if isinstance(mileage, dict):
                mileage = mileage.get("value")
            mileage = int(mileage) if mileage else None

            url = data.get("url", "")
            if url and not url.startswith("http"):
                url = f"https://www.carfax.com{url}"

            return Listing(
                source="carfax",
                title=name,
                price=price,
                mileage=mileage,
                trim=self._extract_trim(name, params),
                url=url,
                is_dealer=True,
            )
        except Exception:
            return None

    def _extract_trim(self, title: str, params: SearchParams) -> str | None:
        remaining = title.lower()
        for word in [str(params.year), params.make_lower, params.model_lower]:
            remaining = remaining.replace(word, "").strip()
        remaining = remaining.strip(" -,")
        return remaining.upper() if remaining and len(remaining) < 30 else None

    @staticmethod
    def _parse_price(text: str) -> int | None:
        match = re.search(r'[\$]?\s*([\d,]+)', text.replace(" ", ""))
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                return None
        return None
