from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from carprice.scraper_base import ScraperBase
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)

# Major Craigslist city subdomains mapped to approximate regions
# In practice we search a few cities near the user's zip
CL_CITIES = [
    "newyork", "losangeles", "chicago", "houston", "phoenix",
    "philadelphia", "sanantonio", "sandiego", "dallas", "sfbay",
    "austin", "seattle", "denver", "boston", "nashville",
    "atlanta", "portland", "miami", "minneapolis", "detroit",
    "stlouis", "tampa", "raleigh", "charlotte", "indianapolis",
    "columbus", "sacramento", "orangecounty", "inlandempire", "washingtondc",
]


class CraigslistScraper(ScraperBase):
    name = "craigslist"

    def search(self, params: SearchParams) -> list[Listing]:
        listings = []

        # Try to find nearby CL cities using pgeocode
        cities_to_search = self._get_nearby_cities(params.zip_code, limit=5)

        for city in cities_to_search:
            try:
                city_listings = self._search_city(city, params)
                listings.extend(city_listings)
                self._delay()
            except Exception as e:
                logger.warning(f"[craigslist] Failed for {city}: {e}")
                continue

        logger.info(f"[craigslist] Found {len(listings)} listings across {len(cities_to_search)} cities")
        return listings

    def _search_city(self, city: str, params: SearchParams) -> list[Listing]:
        """Search a single Craigslist city subdomain."""
        query = f"{params.make} {params.model}"
        if params.trim:
            query += f" {params.trim}"

        url = (
            f"https://{city}.craigslist.org/search/cta"
            f"?query={query.replace(' ', '+')}"
            f"&min_auto_year={params.year}"
            f"&max_auto_year={params.year}"
            f"&sort=date"
            f"&postal={params.zip_code}"
            f"&search_distance={params.radius_miles}"
        )

        try:
            resp = self._get(url)
            results = self._parse_results(resp.text, city, params)
            if results:
                return results
        except Exception as e:
            logger.debug(f"[craigslist] Requests failed for {city}: {e}")

        # Browser fallback
        try:
            from carprice.browser import create_driver
            driver = create_driver()
            try:
                driver.get(url)
                self._delay()
                return self._parse_results(driver.page_source, city, params)
            finally:
                driver.quit()
        except Exception as e:
            logger.debug(f"[craigslist] Browser fallback failed for {city}: {e}")

        return []

    def _parse_results(self, html: str, city: str, params: SearchParams) -> list[Listing]:
        """Parse Craigslist search results HTML."""
        listings = []
        soup = BeautifulSoup(html, "lxml")

        # Craigslist uses different HTML structures over time
        results = (
            soup.select("div.cl-search-result")
            or soup.select("li.cl-static-search-result")
            or soup.select(".result-row")
        )

        for result in results:
            try:
                # Title: from data attribute or link text
                title = result.get("title", "")

                # Link: find the listing link
                title_el = result.select_one("a.titlestring") or result.select_one(".gallery-card a.main")
                if not title_el and not title:
                    continue

                if title_el:
                    if not title:
                        title = title_el.get_text(strip=True)
                    href = title_el.get("href", "")
                else:
                    # Grab any link
                    any_a = result.select_one("a[href*='craigslist']")
                    href = any_a.get("href", "") if any_a else ""

                url = href if href.startswith("http") else f"https://{city}.craigslist.org{href}"

                # Price
                price_el = result.select_one(".priceinfo") or result.select_one(".result-price") or result.select_one("span.price")
                if not price_el:
                    continue
                price = self._parse_price(price_el.get_text(strip=True))
                if not price:
                    continue

                # Location from .result-location or .meta
                loc_el = result.select_one(".result-location") or result.select_one(".meta")
                location = city
                if loc_el:
                    loc_text = loc_el.get_text(strip=True).strip("+ ")
                    if loc_text:
                        location = loc_text

                # Mileage - extract from meta text or title
                meta_el = result.select_one(".meta")
                meta_text = meta_el.get_text(strip=True) if meta_el else ""
                mileage = self._extract_mileage_from_text(meta_text) or self._extract_mileage_from_text(title)

                # Trim
                trim = self._extract_trim(title, params)

                listings.append(Listing(
                    source="craigslist",
                    title=title,
                    price=price,
                    mileage=mileage,
                    trim=trim,
                    location=location,
                    dealer_name=None,
                    is_dealer=False,
                    url=url,
                ))

            except Exception as e:
                logger.debug(f"[craigslist] Failed to parse result: {e}")
                continue

        return listings

    def _get_nearby_cities(self, zip_code: str, limit: int = 5) -> list[str]:
        """Get nearby Craigslist city subdomains based on zip code."""
        try:
            import pgeocode
            nomi = pgeocode.Nominatim("us")
            result = nomi.query_postal_code(zip_code)

            if result is not None and hasattr(result, "state_code"):
                state = str(result.state_code).lower() if result.state_code else ""
                # Simple state-to-CL-cities mapping for top states
                state_cities = {
                    "ca": ["sfbay", "losangeles", "sandiego", "sacramento", "orangecounty", "inlandempire"],
                    "ny": ["newyork"],
                    "tx": ["houston", "dallas", "sanantonio", "austin"],
                    "fl": ["miami", "tampa"],
                    "il": ["chicago"],
                    "pa": ["philadelphia"],
                    "az": ["phoenix"],
                    "wa": ["seattle"],
                    "co": ["denver"],
                    "ma": ["boston"],
                    "tn": ["nashville"],
                    "ga": ["atlanta"],
                    "or": ["portland"],
                    "mn": ["minneapolis"],
                    "mi": ["detroit"],
                    "mo": ["stlouis"],
                    "nc": ["raleigh", "charlotte"],
                    "in": ["indianapolis"],
                    "oh": ["columbus"],
                    "dc": ["washingtondc"],
                }
                cities = state_cities.get(state, [])
                if cities:
                    return cities[:limit]
        except Exception as e:
            logger.debug(f"[craigslist] pgeocode lookup failed: {e}")

        # Fallback: search a few major cities
        return CL_CITIES[:limit]

    def _extract_trim(self, title: str, params: SearchParams) -> str | None:
        remaining = title.lower()
        for word in [str(params.year), params.make_lower, params.model_lower]:
            remaining = remaining.replace(word, "").strip()
        remaining = remaining.strip(" -,")
        return remaining.upper() if remaining and len(remaining) < 30 else None

    @staticmethod
    def _parse_price(text: str) -> int | None:
        match = re.search(r'\$\s*([\d,]+)', text)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_mileage_from_text(text: str) -> int | None:
        match = re.search(r'([\d,]+)\s*(?:mi|miles|k)', text.lower())
        if match:
            try:
                val = match.group(1).replace(",", "")
                result = int(val)
                # If it looks like "45k", multiply
                if "k" in text.lower()[match.start():match.end()]:
                    result *= 1000
                return result
            except ValueError:
                return None
        return None
