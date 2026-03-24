from __future__ import annotations

import logging
from carprice.models import Listing, SearchParams

logger = logging.getLogger(__name__)


def normalize_listings(listings: list[Listing], params: SearchParams) -> list[Listing]:
    """Normalize, filter, and deduplicate listings."""
    normalized = []

    for listing in listings:
        # Filter out unreasonable prices
        if listing.price < 500 or listing.price > 500_000:
            logger.debug(f"Filtered outlier price: {listing.price} from {listing.source}")
            continue

        # Filter by mileage tolerance if mileage is known
        if listing.mileage is not None:
            low = params.mileage - params.mileage_tolerance
            high = params.mileage + params.mileage_tolerance
            if listing.mileage < max(0, low) or listing.mileage > high:
                logger.debug(f"Filtered by mileage: {listing.mileage} from {listing.source}")
                continue

        # Filter by trim if specified
        if params.trim_lower and listing.trim:
            # Keep listings that mention the trim, or have no trim info
            if params.trim_lower not in listing.trim.lower():
                # Check title too
                if params.trim_lower not in listing.title.lower():
                    continue

        normalized.append(listing)

    # Deduplicate by (price, mileage, first few chars of dealer)
    seen = set()
    deduped = []
    for listing in normalized:
        key = (
            listing.price,
            listing.mileage,
            (listing.dealer_name or "")[:10].lower(),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(listing)
        else:
            logger.debug(f"Deduped listing: {listing.title} from {listing.source}")

    logger.info(f"Normalized {len(listings)} -> {len(deduped)} listings")
    return deduped
