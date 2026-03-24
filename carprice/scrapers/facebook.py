from __future__ import annotations

import logging

from carprice.scraper_base import ScraperBase
from carprice.models import SearchParams, Listing

logger = logging.getLogger(__name__)


class FacebookScraper(ScraperBase):
    """
    Facebook Marketplace scraper — stub implementation.

    Facebook Marketplace requires authentication and has very aggressive anti-bot
    detection. Accounts used for scraping risk suspension.

    To use this scraper in the future:
    1. Provide Facebook cookies via FACEBOOK_COOKIES env var or --fb-cookies flag
    2. Accept the risk of account restrictions
    """
    name = "facebook"
    requires_browser = True

    def search(self, params: SearchParams) -> list[Listing]:
        logger.warning(
            "[facebook] Facebook Marketplace scraping is not yet implemented. "
            "FB requires login and has aggressive anti-bot detection. "
            "Use --include-facebook to opt in once support is added."
        )
        return []
