# State management
from typing import TypedDict, List, Dict, Optional


class ArtisanProfile(TypedDict):
    artisan_type: str
    location: str
    budget_level: str
    production_capacity: int
    target_market: Optional[str]


class SearchResult(TypedDict):
    title: str
    snippet: str
    source: str


class MarketplaceProduct(TypedDict):
    title: str
    price: float
    rating: float
    reviews: int
    platform: str


class IntelligenceMetrics(TypedDict):
    demand_score: float
    competition_score: float
    trend_momentum_score: float
    geo_strength_score: float
    profitability_score: float
    opportunity_index: float


class StrategyOutput(TypedDict):
    recommended_products: List[Dict]
    summary: str
    confidence_score: float


class SystemMeta(TypedDict):
    execution_time: Optional[float]
    model_used: str
    version: str
    errors: List[str]


class MarketState(TypedDict):
    # 1️⃣ Artisan Profile
    artisan_profile: ArtisanProfile

    # 2️⃣ Raw Data
    search_results: List[SearchResult]
    marketplace_data: List[MarketplaceProduct]

    # 3️⃣ Processed Intelligence
    extracted_trends: List[str]
    competitor_insights: List[str]

    # 4️⃣ Scoring
    metrics: IntelligenceMetrics

    # 5️⃣ Final Output
    strategy: Optional[StrategyOutput]

    # 6️⃣ System Metadata
    system: SystemMeta