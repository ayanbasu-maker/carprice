from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import quote

from carprice.scraper_base import ScraperBase
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)


class CarGurusScraper(ScraperBase):
    name = "cargurus"

    def search(self, params: SearchParams) -> list[Listing]:
        make = params.make_lower
        model = params.model_lower

        # CarGurus SEO-friendly search URL with make/model
        url = (
            f"https://www.cargurus.com/Cars/l-Used-{params.year}-"
            f"{quote(make.title().replace(' ', '-'))}-"
            f"{quote(model.title().replace(' ', '-'))}-"
            f"t{self._get_trim_slug(params)}"
            f"_z{params.zip_code}"
            f"_d{params.radius_miles}"
        )

        # Also try the standard search URL
        search_url = (
            f"https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action"
            f"?zip={params.zip_code}"
            f"&showNegotiable=true&sortDir=ASC&sortType=DEAL_SCORE"
            f"&distance={params.radius_miles}"
            f"&minYear={params.year}&maxYear={params.year}"
            f"&searchChanged=true&filtersModified=true"
        )

        # Use browser — plain requests get 403
        listings = self._scrape_with_browser(search_url, params)

        if not listings:
            self._delay()
            listings = self._scrape_with_browser(url, params)

        logger.info(f"[cargurus] Found {len(listings)} listings")
        return listings

    def _scrape_with_browser(self, url: str, params: SearchParams) -> list[Listing]:
        from carprice.browser import create_driver

        driver = create_driver()
        try:
            driver.get(url)
            time.sleep(8)

            # Extract listings via JS — CarGurus uses React with obfuscated class names
            raw = driver.execute_script('''
                var listings = [];
                // Find all card elements (they have price elements inside)
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
                    // Walk up to find the card container
                    var card = el;
                    for (var j = 0; j < 8; j++) {
                        if (!card.parentElement) break;
                        card = card.parentElement;
                        var links = card.querySelectorAll('a[href*="/details/"], a[href*="inventorylisting"]');
                        if (links.length > 0) break;
                    }

                    var links = card.querySelectorAll('a[href*="/details/"], a[href*="inventorylisting"]');
                    var link = links.length > 0 ? links[0].href : '';

                    // Deduplicate by link
                    if (link && seen.has(link)) continue;
                    if (link) seen.add(link);

                    var text = card.textContent || '';
                    var priceVal = el.textContent.trim().replace(/[\\$,]/g, '');

                    // Extract title — usually the year+make+model text
                    var titleMatch = text.match(/(\\d{4}\\s+\\w[\\w\\s]+)/);
                    var title = titleMatch ? titleMatch[1].trim().substring(0, 80) : '';

                    // Extract mileage
                    var mileageMatch = text.match(/([\\d,]+)\\s*mi/);

                    // Extract dealer
                    var dealerMatch = text.match(/(?:Sponsored by|Dealer[:\\s]+)([^\\n]+)/i);

                    listings.push({
                        price: priceVal,
                        title: title,
                        link: link,
                        mileage: mileageMatch ? mileageMatch[1].replace(/,/g, '') : '',
                        dealer: dealerMatch ? dealerMatch[1].trim().substring(0, 50) : ''
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
                        source="cargurus",
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
                    logger.debug(f"[cargurus] Failed to parse item: {e}")

            return listings
        except Exception as e:
            logger.warning(f"[cargurus] Browser scrape failed: {e}")
            return []
        finally:
            driver.quit()

    def _extract_trim(self, title: str, params: SearchParams) -> str | None:
        remaining = title.lower()
        for word in [str(params.year), params.make_lower, params.model_lower]:
            remaining = remaining.replace(word, "").strip()
        remaining = remaining.strip(" -,")
        return remaining.upper() if remaining and len(remaining) < 30 else None

    def _get_trim_slug(self, params: SearchParams) -> str:
        if params.trim:
            return f"_{params.trim.upper()}"
        return ""
