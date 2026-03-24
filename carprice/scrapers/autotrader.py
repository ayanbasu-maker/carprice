from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote

from carprice.scraper_base import ScraperBase
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)


class AutoTraderScraper(ScraperBase):
    name = "autotrader"
    requires_browser = True

    def search(self, params: SearchParams) -> list[Listing]:
        make = params.make_lower
        model = params.model_lower

        url = (
            f"https://www.autotrader.com/cars-for-sale/all-cars/"
            f"{quote(make)}/{quote(model)}"
            f"?zip={params.zip_code}"
            f"&searchRadius={params.radius_miles}"
            f"&startYear={params.year}"
            f"&endYear={params.year}"
            f"&sortBy=derivedpriceDESC"
            f"&numRecords=25"
        )

        listings = self._scrape_with_browser(url, params)
        logger.info(f"[autotrader] Found {len(listings)} listings")
        return listings

    def _scrape_with_browser(self, url: str, params: SearchParams) -> list[Listing]:
        from carprice.browser import create_driver

        driver = create_driver()
        try:
            driver.get(url)
            time.sleep(10)

            title = driver.title
            if "unavailable" in title.lower() or "blocked" in title.lower():
                logger.warning("[autotrader] Page blocked by bot detection")
                return []

            raw = driver.execute_script('''
                var listings = [];
                // AutoTrader uses inventory listing cards
                var cards = document.querySelectorAll('[data-cmp="inventoryListing"], [class*="inventory-listing"]');

                // Fallback: find cards by looking for price elements
                if (cards.length === 0) {
                    var allEls = document.querySelectorAll('*');
                    var priceEls = [];
                    for (var i = 0; i < allEls.length; i++) {
                        var t = (allEls[i].innerText || '').trim();
                        if (t.match(/^\\$[\\d,]+$/) && t.length < 15) {
                            priceEls.push(allEls[i]);
                        }
                    }

                    var seen = new Set();
                    for (var i = 0; i < priceEls.length; i++) {
                        var el = priceEls[i];
                        var card = el;
                        for (var j = 0; j < 10; j++) {
                            if (!card.parentElement) break;
                            card = card.parentElement;
                            if (card.querySelector('a[href*="vehicledetails"]')) break;
                        }

                        var link = '';
                        var linkEl = card.querySelector('a[href*="vehicledetails"]');
                        if (linkEl) link = linkEl.href;
                        if (link && seen.has(link)) continue;
                        if (link) seen.add(link);

                        var text = card.textContent || '';
                        var mileageMatch = text.match(/([\d,]+)\s*mi/);
                        var titleEl = card.querySelector('h2, h3, [data-cmp="subheading"]');
                        var title = titleEl ? titleEl.textContent.trim() : '';

                        listings.push({
                            price: el.textContent.trim().replace(/[\\$,]/g, ''),
                            title: title.substring(0, 100),
                            link: link,
                            mileage: mileageMatch ? mileageMatch[1].replace(/,/g, '') : ''
                        });
                    }
                    return listings;
                }

                for (var i = 0; i < cards.length; i++) {
                    var card = cards[i];
                    var text = card.textContent || '';

                    var priceMatch = text.match(/\\$([\\d,]+)/);
                    if (!priceMatch) continue;

                    var titleEl = card.querySelector('h2, [data-cmp="subheading"]');
                    var linkEl = card.querySelector('a[href*="vehicledetails"]');
                    var mileageMatch = text.match(/([\\d,]+)\\s*mi/);

                    listings.push({
                        price: priceMatch[1].replace(/,/g, ''),
                        title: titleEl ? titleEl.textContent.trim().substring(0, 100) : '',
                        link: linkEl ? linkEl.href : '',
                        mileage: mileageMatch ? mileageMatch[1].replace(/,/g, '') : ''
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
                        source="autotrader",
                        title=title,
                        price=price,
                        mileage=mileage,
                        trim=trim,
                        location=None,
                        dealer_name=None,
                        is_dealer=True,
                        url=item.get("link", ""),
                    ))
                except (ValueError, KeyError) as e:
                    logger.debug(f"[autotrader] Failed to parse item: {e}")

            return listings
        except Exception as e:
            logger.warning(f"[autotrader] Browser scrape failed: {e}")
            return []
        finally:
            driver.quit()

    def _extract_trim(self, title: str, params: SearchParams) -> str | None:
        remaining = title.lower()
        for word in [str(params.year), params.make_lower, params.model_lower]:
            remaining = remaining.replace(word, "").strip()
        remaining = remaining.strip(" -,")
        return remaining.upper() if remaining and len(remaining) < 30 else None
