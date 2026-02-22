# Scoring engine
from typing import Dict


# -----------------------------
# Helper Normalization Function
# -----------------------------
def normalize(value: float, min_val: float = 0, max_val: float = 100) -> float:
    """
    Normalize value safely between 0 and 100.
    """
    if max_val == min_val:
        return 0
    normalized = (value - min_val) / (max_val - min_val)
    return max(0, min(normalized * 100, 100))


# -----------------------------
# Core Scoring Function
# -----------------------------
def calculate_scores(metrics: Dict) -> Dict:
    """
    Calculate final production-grade opportunity scores.

    Expected metrics input:
    {
        "trend_momentum_score": 0-100,
        "competition_score": 0-100,
        "geo_strength_score": 0-100 (optional),
        "profitability_score": 0-100 (optional)
    }
    """

    # Extract safely with defaults
    trend_score = metrics.get("trend_momentum_score", 0)
    competition_score = metrics.get("competition_score", 50)
    geo_strength_score = metrics.get("geo_strength_score", 50)
    profitability_score = metrics.get("profitability_score", 50)

    # Normalize everything
    trend_score = normalize(trend_score)
    competition_score = normalize(competition_score)
    geo_strength_score = normalize(geo_strength_score)
    profitability_score = normalize(profitability_score)

    # -----------------------------
    # Weighted Formula
    # -----------------------------
    # Production logic:
    # Demand + Geo + Profit increases opportunity
    # Competition reduces opportunity

    weighted_demand = trend_score * 0.4
    weighted_geo = geo_strength_score * 0.2
    weighted_profit = profitability_score * 0.2
    weighted_competition = competition_score * 0.2

    # Core opportunity calculation
    opportunity_raw = (
        weighted_demand +
        weighted_geo +
        weighted_profit
    ) - weighted_competition

    # Final normalization
    opportunity_index = max(0, min(opportunity_raw, 100))

    # Risk classification
    if opportunity_index >= 70:
        level = "High Opportunity"
    elif opportunity_index >= 40:
        level = "Moderate Opportunity"
    else:
        level = "Low Opportunity"

    return {
        "trend_momentum_score": trend_score,
        "competition_score": competition_score,
        "geo_strength_score": geo_strength_score,
        "profitability_score": profitability_score,
        "opportunity_index": opportunity_index,
        "opportunity_level": level
    }