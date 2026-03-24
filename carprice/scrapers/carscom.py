from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from carprice.scraper_base import ScraperBase
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)


class CarsComScraper(ScraperBase):
    name = "carscom"

    def search(self, params: SearchParams) -> list[Listing]:
        make = params.make_lower
        model = params.model_lower

        url = (
            f"https://www.cars.com/shopping/results/"
            f"?stock_type=used"
            f"&makes[]={make}"
            f"&models[]={make}-{model}"
            f"&year_min={params.year}"
            f"&year_max={params.year}"
            f"&maximum_distance={params.radius_miles}"
            f"&zip={params.zip_code}"
        )

        if params.trim:
            url += f"&trims[]={make}-{model}-{params.trim.lower()}"

        listings = self._scrape_with_browser(url, params)

        # Try page 2
        if listings:
            try:
                self._delay()
                page2 = self._scrape_with_browser(url + "&page=2", params)
                listings.extend(page2)
            except Exception:
                pass

        logger.info(f"[carscom] Found {len(listings)} listings")
        return listings

    def _scrape_with_browser(self, url: str, params: SearchParams) -> list[Listing]:
        """Use browser + JS to extract listings from Cars.com web components."""
        from carprice.browser import create_driver
        import time

        driver = create_driver()
        try:
            driver.get(url)
            time.sleep(8)

            raw = driver.execute_script('''
                var listings = [];
                var cards = document.querySelectorAll('fuse-card');
                for (var i = 0; i < cards.length; i++) {
                    var card = cards[i];
                    var text = card.textContent;
                    var priceMatch = text.match(/\\$([\d,]+)/);
                    if (!priceMatch) continue;

                    var links = card.querySelectorAll('a[href*=vehicledetail]');
                    var link = links.length > 0 ? links[0].href : '';
                    var title = links.length > 0 ? links[0].textContent.trim() : '';

                    var mileageMatch = text.match(/([\d,]+)\\s*mi/);
                    var dealerEl = card.querySelector('[class*=dealer]');

                    listings.push({
                        price: priceMatch[1].replace(/,/g, ''),
                        title: title.substring(0, 100),
                        link: link,
                        mileage: mileageMatch ? mileageMatch[1].replace(/,/g, '') : '',
                        dealer: dealerEl ? dealerEl.textContent.trim() : ''
                    });
                }
                return listings;
            ''')

            listings = []
            for item in raw:
                try:
                    price = int(item["price"])
                    if price < 500:
                        continue
                    title = item["title"] or f"{params.year} {params.make} {params.model}"
                    mileage = int(item["mileage"]) if item.get("mileage") else None
                    trim = self._extract_trim(title, params)

                    listings.append(Listing(
                        source="carscom",
                        title=title,
                        price=price,
                        mileage=mileage,
                        trim=trim,
                        location=None,
                        dealer_name=item.get("dealer") or None,
                        is_dealer=True,
                        url=item.get("link", ""),
                    ))
                except (ValueError, KeyError) as e:
                    logger.debug(f"[carscom] Failed to parse item: {e}")

            return listings
        except Exception as e:
            logger.warning(f"[carscom] Browser scrape failed: {e}")
            return []
        finally:
            driver.quit()

    def _extract_trim(self, title: str, params: SearchParams) -> str | None:
        remaining = title.lower()
        for word in ["used", str(params.year), params.make_lower, params.model_lower]:
            remaining = remaining.replace(word, "").strip()
        remaining = remaining.strip(" -,")
        return remaining.upper() if remaining and len(remaining) < 30 else None
