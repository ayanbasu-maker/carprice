from __future__ import annotations

import statistics
import logging
from carprice.models import Listing, SearchParams, PriceReport

logger = logging.getLogger(__name__)


def analyze(
    listings: list[Listing],
    params: SearchParams,
    sources_searched: list[str],
    sources_failed: list[str],
    kbb_value: dict | None = None,
) -> PriceReport:
    """Analyze listings and produce a price report with recommendation."""

    prices = sorted([l.price for l in listings])

    if not prices:
        return PriceReport(
            search_params=params,
            listings=listings,
            average_price=0,
            median_price=0,
            price_low=0,
            price_high=0,
            recommended_price=0,
            total_listings=0,
            sources_searched=sources_searched,
            sources_failed=sources_failed,
            kbb_value=kbb_value,
        )

    # Basic stats
    avg = statistics.mean(prices)
    median = statistics.median(prices)

    # Percentiles
    p10 = _percentile(prices, 0.10)
    p25 = _percentile(prices, 0.25)
    p90 = _percentile(prices, 0.90)

    # Remove outliers using IQR
    cleaned_prices = _remove_outliers(prices)
    if cleaned_prices:
        clean_median = statistics.median(cleaned_prices)
        clean_p25 = _percentile(cleaned_prices, 0.25)
    else:
        clean_median = median
        clean_p25 = p25

    # Recommended price calculation
    if kbb_value and "fair" in kbb_value:
        kbb_fair = kbb_value["fair"]
        recommended = 0.4 * kbb_fair + 0.3 * clean_median + 0.3 * clean_p25
    else:
        recommended = 0.5 * clean_median + 0.5 * clean_p25

    # Dealer vs private party split
    dealer_prices = sorted([l.price for l in listings if l.is_dealer])
    private_prices = sorted([l.price for l in listings if not l.is_dealer])

    dealer_rec = None
    private_rec = None

    if dealer_prices:
        d_median = statistics.median(dealer_prices)
        d_p25 = _percentile(dealer_prices, 0.25)
        dealer_rec = 0.5 * d_median + 0.5 * d_p25

    if private_prices:
        p_median = statistics.median(private_prices)
        p_p25 = _percentile(private_prices, 0.25)
        private_rec = 0.5 * p_median + 0.5 * p_p25

    return PriceReport(
        search_params=params,
        listings=listings,
        average_price=avg,
        median_price=median,
        price_low=p10,
        price_high=p90,
        recommended_price=recommended,
        total_listings=len(listings),
        sources_searched=sources_searched,
        sources_failed=sources_failed,
        kbb_value=kbb_value,
        dealer_recommendation=dealer_rec,
        private_recommendation=private_rec,
    )


def _percentile(sorted_data: list[int | float], pct: float) -> int:
    """Calculate percentile from sorted data."""
    if not sorted_data:
        return 0
    idx = int(len(sorted_data) * pct)
    idx = max(0, min(idx, len(sorted_data) - 1))
    return int(sorted_data[idx])


def _remove_outliers(prices: list[int]) -> list[int]:
    """Remove outliers using IQR method."""
    if len(prices) < 4:
        return prices

    q1 = _percentile(prices, 0.25)
    q3 = _percentile(prices, 0.75)
    iqr = q3 - q1

    if iqr == 0:
        return prices

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    return [p for p in prices if lower <= p <= upper]
