"""Vercel serverless function for car price search."""
from __future__ import annotations

import json
import logging
import re
import statistics
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from http.server import BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def _headers(referer: str = "https://www.google.com/"):
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": referer,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }


def _get(url: str, session: requests.Session, timeout: int = 20, referer: str = "https://www.google.com/") -> requests.Response:
    session.headers.update(_headers(referer))
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    source: str
    title: str
    price: int
    url: str
    mileage: Optional[int] = None
    trim: Optional[str] = None
    location: Optional[str] = None
    dealer_name: Optional[str] = None
    is_dealer: bool = True


# ---------------------------------------------------------------------------
# Scrapers (requests-only, no browser)
# ---------------------------------------------------------------------------

CL_STATE_CITIES = {
    "ca": ["sfbay", "losangeles", "sandiego", "sacramento", "orangecounty", "inlandempire"],
    "ny": ["newyork"], "tx": ["houston", "dallas", "sanantonio", "austin"],
    "fl": ["miami", "tampa"], "il": ["chicago"], "pa": ["philadelphia"],
    "az": ["phoenix"], "wa": ["seattle"], "co": ["denver"], "ma": ["boston"],
    "tn": ["nashville"], "ga": ["atlanta"], "or": ["portland"],
    "mn": ["minneapolis"], "mi": ["detroit"], "mo": ["stlouis"],
    "nc": ["raleigh", "charlotte"], "oh": ["columbus"], "dc": ["washingtondc"],
}

CL_DEFAULT = ["sfbay", "losangeles", "chicago", "newyork", "houston"]


def _get_cl_cities(zip_code: str, limit: int = 3) -> list[str]:
    try:
        import pgeocode
        nomi = pgeocode.Nominatim("us")
        result = nomi.query_postal_code(zip_code)
        if result is not None and hasattr(result, "state_code"):
            state = str(result.state_code).lower() if result.state_code else ""
            cities = CL_STATE_CITIES.get(state, [])
            if cities:
                return cities[:limit]
    except Exception:
        pass
    return CL_DEFAULT[:limit]


def _extract_trim(title: str, year: int, make: str, model: str) -> Optional[str]:
    remaining = title.lower()
    for word in [str(year), make.lower(), model.lower(), "used", "certified"]:
        remaining = remaining.replace(word, "").strip()
    remaining = remaining.strip(" -,")
    return remaining.upper() if remaining and len(remaining) < 30 else None


def scrape_craigslist(year: int, make: str, model: str, trim: str, mileage: int,
                      zip_code: str, radius: int) -> list[Listing]:
    """Scrape Craigslist — works with plain requests."""
    session = requests.Session()
    listings = []
    cities = _get_cl_cities(zip_code, limit=3)

    query = f"{make} {model}"
    if trim:
        query += f" {trim}"

    for city in cities:
        try:
            url = (
                f"https://{city}.craigslist.org/search/cta"
                f"?query={query.replace(' ', '+')}"
                f"&min_auto_year={year}&max_auto_year={year}"
                f"&sort=date&postal={zip_code}"
                f"&search_distance={radius}"
            )
            resp = _get(url, session)
            soup = BeautifulSoup(resp.text, "lxml")

            results = (
                soup.select("div.cl-search-result")
                or soup.select("li.cl-static-search-result")
                or soup.select(".result-row")
            )

            for result in results:
                try:
                    card_title = result.get("title", "")
                    title_el = result.select_one("a.titlestring") or result.select_one(".gallery-card a.main")
                    if title_el:
                        if not card_title:
                            card_title = title_el.get_text(strip=True)
                        href = title_el.get("href", "")
                    else:
                        any_a = result.select_one("a[href*='craigslist']")
                        href = any_a.get("href", "") if any_a else ""

                    link = href if href.startswith("http") else f"https://{city}.craigslist.org{href}"

                    price_el = result.select_one(".priceinfo") or result.select_one(".result-price")
                    if not price_el:
                        continue
                    price_match = re.search(r'\$([\d,]+)', price_el.get_text(strip=True))
                    if not price_match:
                        continue
                    price = int(price_match.group(1).replace(",", ""))
                    if price < 500:
                        continue

                    meta_el = result.select_one(".meta")
                    meta_text = meta_el.get_text(strip=True) if meta_el else ""
                    mi_match = re.search(r'([\d,]+)\s*(?:mi|k\s*mi)', meta_text.lower() + " " + card_title.lower())
                    mi = int(mi_match.group(1).replace(",", "")) if mi_match else None

                    loc_el = result.select_one(".result-location")
                    location = loc_el.get_text(strip=True).strip("+ ") if loc_el else city

                    listings.append(Listing(
                        source="craigslist",
                        title=card_title,
                        price=price,
                        mileage=mi,
                        trim=_extract_trim(card_title, year, make, model),
                        location=location,
                        is_dealer=False,
                        url=link,
                    ))
                except Exception:
                    continue

            time.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.warning(f"CL {city} failed: {e}")
            continue

    return listings


def scrape_cargurus(year: int, make: str, model: str, trim: str, mileage: int,
                    zip_code: str, radius: int) -> list[Listing]:
    """Attempt CarGurus search results API."""
    session = requests.Session()
    listings = []

    # Try the search results page
    search_query = quote(f"{year} {make} {model}")
    url = (
        f"https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action"
        f"?zip={zip_code}&inventorySearchWidgetType=AUTO&searchChanged=true"
        f"&sortDir=ASC&sortType=DEAL_SCORE&distance={radius}"
        f"&minYear={year}&maxYear={year}&filtersModified=true"
    )

    try:
        # First visit the homepage to get cookies
        session.headers.update(_headers("https://www.google.com/"))
        session.get("https://www.cargurus.com/", timeout=10)
        time.sleep(0.5)

        resp = _get(url, session, referer="https://www.cargurus.com/")
        html = resp.text

        # Try embedded JSON - multiple patterns
        json_patterns = [
            r'"listings"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
            r'"inventoryListings"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
            r'"results"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
            r'initialState\s*=\s*\{.*?"listings"\s*:\s*(\[[\s\S]*?\])',
        ]
        for pattern in json_patterns:
            if listings:
                break
            matches = re.findall(pattern, html)
            for match in matches:
                try:
                    data = json.loads(match)
                    for item in data:
                        price = item.get("price") or item.get("listPrice") or item.get("expectedPrice")
                        if not price or int(price) < 500:
                            continue
                        listings.append(Listing(
                            source="cargurus",
                            title=item.get("listingTitle") or item.get("name") or f"{year} {make} {model}",
                            price=int(price),
                            mileage=int(item["mileage"]) if item.get("mileage") else None,
                            trim=item.get("trimName") or _extract_trim(item.get("listingTitle", ""), year, make, model),
                            location=item.get("locationString") or item.get("sellerCity"),
                            dealer_name=item.get("sellerName"),
                            is_dealer=True,
                            url=f"https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action?listingId={item.get('id', '')}",
                        ))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

        # HTML fallback
        if not listings:
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("[data-cg-ft='car-blade']") or soup.select(".listing-row") or soup.select("article")
            for card in cards:
                try:
                    price_el = card.select_one("[data-cg-ft='car-blade-price']") or card.select_one(".price") or card.select_one("[class*='price']")
                    if not price_el:
                        continue
                    pm = re.search(r'[\d,]+', price_el.get_text().replace("$", ""))
                    if not pm:
                        continue
                    price = int(pm.group().replace(",", ""))
                    if price < 500:
                        continue

                    title_el = card.select_one("h4") or card.select_one("h2") or card.select_one("a")
                    title = title_el.get_text(strip=True) if title_el else f"{year} {make} {model}"

                    link_el = card.select_one("a[href]")
                    href = link_el["href"] if link_el else ""
                    link = href if href.startswith("http") else f"https://www.cargurus.com{href}"

                    listings.append(Listing(
                        source="cargurus",
                        title=title,
                        price=price,
                        trim=_extract_trim(title, year, make, model),
                        is_dealer=True,
                        url=link,
                    ))
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"CarGurus failed: {e}")

    return listings


def scrape_carscom(year: int, make: str, model: str, trim: str, mileage: int,
                   zip_code: str, radius: int) -> list[Listing]:
    """Attempt Cars.com with requests."""
    session = requests.Session()
    listings = []
    mk = make.lower()
    md = model.lower()

    url = (
        f"https://www.cars.com/shopping/results/"
        f"?stock_type=used&makes[]={mk}&models[]={mk}-{md}"
        f"&year_min={year}&year_max={year}"
        f"&maximum_distance={radius}&zip={zip_code}"
    )
    if trim:
        url += f"&trims[]={mk}-{md}-{trim.lower()}"

    try:
        # Visit homepage first for cookies
        session.headers.update(_headers("https://www.google.com/"))
        session.get("https://www.cars.com/", timeout=10)
        time.sleep(0.3)

        resp = _get(url, session, referer="https://www.cars.com/")
        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select(".vehicle-card") or soup.select("[class*='vehicle-card']") or soup.select("[data-qa='results-card']")

        for card in cards:
            try:
                title_el = card.select_one("a.vehicle-card-visited-tracking-link") or card.select_one("h2") or card.select_one("[class*='title']")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)

                price_el = card.select_one(".primary-price") or card.select_one("[class*='primary-price']") or card.select_one("[class*='price']")
                if not price_el:
                    continue
                pm = re.search(r'[\d,]+', price_el.get_text().replace("$", ""))
                if not pm:
                    continue
                price = int(pm.group().replace(",", ""))
                if price < 500:
                    continue

                link_el = card.select_one("a[href*='/vehicledetail/']") or card.select_one("a[href*='/vehicle/']")
                href = link_el["href"] if link_el else ""
                link = href if href.startswith("http") else f"https://www.cars.com{href}"

                mileage_el = card.select_one(".mileage") or card.select_one("[class*='mileage']")
                mi = None
                if mileage_el:
                    mm = re.search(r'([\d,]+)', mileage_el.get_text())
                    mi = int(mm.group(1).replace(",", "")) if mm else None

                listings.append(Listing(
                    source="carscom",
                    title=title,
                    price=price,
                    mileage=mi,
                    trim=_extract_trim(title, year, make, model),
                    is_dealer=True,
                    url=link,
                ))
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Cars.com failed: {e}")

    return listings


def scrape_autotrader(year: int, make: str, model: str, trim: str, mileage: int,
                      zip_code: str, radius: int) -> list[Listing]:
    """Attempt AutoTrader with requests."""
    session = requests.Session()
    listings = []

    mk = make.lower().replace(" ", "-")
    md = model.lower().replace(" ", "-")

    url = (
        f"https://www.autotrader.com/cars-for-sale/all-cars/{year}/{make}/{model}"
        f"?zip={zip_code}&searchRadius={radius}&isNewSearch=true&marketExtension=include"
        f"&sortBy=relevance&numRecords=25"
    )

    try:
        session.headers.update(_headers("https://www.google.com/"))
        session.get("https://www.autotrader.com/", timeout=10)
        time.sleep(0.3)

        resp = _get(url, session, referer="https://www.autotrader.com/")
        html = resp.text

        # Extract JSON data from script tags
        json_patterns = [
            r'window\.__BONNET_DATA__\s*=\s*(\{[\s\S]*?\});\s*</script>',
            r'"listings"\s*:\s*(\[[\s\S]*?\])\s*,',
            r'"results"\s*:\s*(\[[\s\S]*?\])\s*,',
        ]

        for pattern in json_patterns:
            if listings:
                break
            matches = re.findall(pattern, html)
            for match in matches:
                try:
                    data = json.loads(match)
                    items = data if isinstance(data, list) else data.get("listings", data.get("results", []))
                    for item in items:
                        price = item.get("pricingDetail", {}).get("primary") if isinstance(item.get("pricingDetail"), dict) else item.get("price") or item.get("listPrice")
                        if not price or int(price) < 500:
                            continue
                        listings.append(Listing(
                            source="autotrader",
                            title=item.get("title") or f"{year} {make} {model}",
                            price=int(price),
                            mileage=int(item.get("mileage") or item.get("specifications", {}).get("mileage", {}).get("value", 0)) or None,
                            trim=item.get("trim") or _extract_trim(item.get("title", ""), year, make, model),
                            location=item.get("location"),
                            dealer_name=item.get("owner", {}).get("name") if isinstance(item.get("owner"), dict) else None,
                            is_dealer=True,
                            url=f"https://www.autotrader.com/cars-for-sale/vehicledetails.xhtml?listingId={item.get('id', '')}",
                        ))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

        # HTML fallback
        if not listings:
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("[data-cmp='inventoryListing']") or soup.select(".inventory-listing")
            for card in cards:
                try:
                    price_el = card.select_one("[data-cmp='firstPrice']") or card.select_one("[class*='first-price']")
                    if not price_el:
                        continue
                    pm = re.search(r'[\d,]+', price_el.get_text().replace("$", ""))
                    if not pm:
                        continue
                    price = int(pm.group().replace(",", ""))
                    if price < 500:
                        continue

                    title_el = card.select_one("h2") or card.select_one("[data-cmp='heading']")
                    title = title_el.get_text(strip=True) if title_el else f"{year} {make} {model}"

                    link_el = card.select_one("a[href*='vehicledetails']")
                    href = link_el["href"] if link_el else ""
                    link = href if href.startswith("http") else f"https://www.autotrader.com{href}"

                    listings.append(Listing(
                        source="autotrader",
                        title=title,
                        price=price,
                        trim=_extract_trim(title, year, make, model),
                        is_dealer=True,
                        url=link,
                    ))
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"AutoTrader failed: {e}")

    return listings


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _percentile(sorted_data: list, pct: float) -> int:
    if not sorted_data:
        return 0
    idx = max(0, min(int(len(sorted_data) * pct), len(sorted_data) - 1))
    return int(sorted_data[idx])


def _remove_outliers(prices: list[int]) -> list[int]:
    if len(prices) < 4:
        return prices
    q1 = _percentile(prices, 0.25)
    q3 = _percentile(prices, 0.75)
    iqr = q3 - q1
    if iqr == 0:
        return prices
    return [p for p in prices if (q1 - 1.5 * iqr) <= p <= (q3 + 1.5 * iqr)]


def normalize_and_analyze(listings: list[Listing], mileage: int, mileage_tol: int = 30000) -> dict:
    # Filter
    filtered = []
    for l in listings:
        if l.price < 500 or l.price > 500000:
            continue
        if l.mileage is not None:
            if l.mileage < max(0, mileage - mileage_tol) or l.mileage > mileage + mileage_tol:
                continue
        filtered.append(l)

    # Dedup
    seen = set()
    deduped = []
    for l in filtered:
        key = (l.price, l.mileage, (l.dealer_name or "")[:10].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(l)

    prices = sorted([l.price for l in deduped])

    if not prices:
        return {
            "listings": [],
            "total_listings": 0,
            "average_price": 0,
            "median_price": 0,
            "price_low": 0,
            "price_high": 0,
            "recommended_price": 0,
        }

    avg = statistics.mean(prices)
    median = statistics.median(prices)
    p10 = _percentile(prices, 0.10)
    p90 = _percentile(prices, 0.90)

    cleaned = _remove_outliers(prices)
    c_median = statistics.median(cleaned) if cleaned else median
    c_p25 = _percentile(cleaned, 0.25) if cleaned else _percentile(prices, 0.25)

    recommended = 0.5 * c_median + 0.5 * c_p25

    return {
        "listings": [
            {
                "source": l.source,
                "title": l.title,
                "price": l.price,
                "mileage": l.mileage,
                "trim": l.trim,
                "location": l.location,
                "dealer_name": l.dealer_name,
                "is_dealer": l.is_dealer,
                "url": l.url,
            }
            for l in deduped
        ],
        "total_listings": len(deduped),
        "average_price": round(avg),
        "median_price": round(median),
        "price_low": p10,
        "price_high": p90,
        "recommended_price": round(recommended),
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        def param(name: str) -> str:
            return qs.get(name, [""])[0]

        year = param("year")
        make = param("make")
        model = param("model")
        trim_val = param("trim")
        mileage = param("mileage")
        zip_code = param("zip_code")

        if not all([year, make, model, mileage, zip_code]):
            self._json_response(400, {"error": "Missing required fields: year, make, model, mileage, zip_code"})
            return

        try:
            year_int = int(year)
            mileage_int = int(mileage)
        except ValueError:
            self._json_response(400, {"error": "year and mileage must be numbers"})
            return

        radius = 100
        all_listings = []
        sources_searched = []
        sources_failed = []

        scrapers = {
            "craigslist": scrape_craigslist,
            "cargurus": scrape_cargurus,
            "carscom": scrape_carscom,
            "autotrader": scrape_autotrader,
        }

        error_details = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(fn, year_int, make, model, trim_val, mileage_int, zip_code, radius): name
                for name, fn in scrapers.items()
            }
            for future in as_completed(futures, timeout=25):
                name = futures[future]
                try:
                    results = future.result(timeout=20)
                    all_listings.extend(results)
                    sources_searched.append(f"{name} ({len(results)})")
                except Exception as e:
                    sources_failed.append(name)
                    error_details[name] = str(e)[:100]

        report = normalize_and_analyze(all_listings, mileage_int)
        report["sources_searched"] = sources_searched
        report["sources_failed"] = sources_failed
        report["debug"] = {
            "raw_count": len(all_listings),
            "errors": error_details,
        }

        self._json_response(200, report)

    def _json_response(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
