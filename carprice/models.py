from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SearchParams:
    year: int
    make: str
    model: str
    mileage: int
    zip_code: str
    trim: Optional[str] = None
    radius_miles: int = 100
    mileage_tolerance: int = 30000  # +/- from target mileage

    @property
    def make_lower(self) -> str:
        return self.make.strip().lower()

    @property
    def model_lower(self) -> str:
        return self.model.strip().lower()

    @property
    def trim_lower(self) -> Optional[str]:
        return self.trim.strip().lower() if self.trim else None


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
    scraped_at: datetime = field(default_factory=datetime.now)

    @property
    def price_str(self) -> str:
        return f"${self.price:,}"

    @property
    def mileage_str(self) -> str:
        if self.mileage is None:
            return "N/A"
        return f"{self.mileage:,} mi"


@dataclass
class PriceReport:
    search_params: SearchParams
    listings: list[Listing]
    average_price: float
    median_price: float
    price_low: int       # 10th percentile
    price_high: int      # 90th percentile
    recommended_price: float
    total_listings: int
    sources_searched: list[str]
    sources_failed: list[str]
    kbb_value: Optional[dict] = None  # {fair, trade_in, private_party}
    dealer_recommendation: Optional[float] = None
    private_recommendation: Optional[float] = None
