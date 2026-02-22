# Graph nodes
from graph.state import MarketState
from tools.search_scraper import fetch_search_results
from tools.marketplace_scraper import fetch_marketplace_results
from intelligence.scoring_engine import calculate_scores
from agents.trend_agent import analyze_trends
from agents.competition_agent import analyze_competition


# -----------------------------------------
# 1️⃣ SEARCH NODE
# -----------------------------------------
def search_node(state: MarketState):
    artisan_type = state["artisan_profile"]["artisan_type"]
    location = state["artisan_profile"]["location"]

    query = f"Best selling {artisan_type} products in {location} 2026 trends"

    results = fetch_search_results(query)

    return {
        "search_results": results
    }

# -----------------------------------------
# 2️⃣ MARKETPLACE NODE
# -----------------------------------------
def marketplace_node(state: MarketState):
    artisan_type = state["artisan_profile"]["artisan_type"]

    products = fetch_marketplace_results(artisan_type)

    return {
        "marketplace_data": products
    }


# -----------------------------------------
# 3️⃣ TREND ANALYSIS NODE
# -----------------------------------------
def trend_analysis_node(state: MarketState):
    search_data = state["search_results"]

    trend_output = analyze_trends(search_data)

    return {
        "extracted_trends": trend_output["trends"],
        "metrics": {
            **state.get("metrics", {}),
            "trend_momentum_score": trend_output["momentum_score"]
        }
    }


 # -----------------------------------------
# 4️⃣ COMPETITION NODE
# -----------------------------------------
def competition_analysis_node(state: MarketState):
    marketplace_data = state["marketplace_data"]

    competition_output = analyze_competition(marketplace_data)

    return {
        "competitor_insights": competition_output["insights"],
        "metrics": {
            **state.get("metrics", {}),
            "competition_score": competition_output["competition_score"]
        }
    }


# -----------------------------------------
# 5️⃣ SCORING NODE
# -----------------------------------------
def scoring_node(state: MarketState):
    metrics = state.get("metrics", {})

    scores = calculate_scores(metrics)

    return {
        "metrics": {
            **metrics,
            **scores
        }
    }


# -----------------------------------------
# 6️⃣ STRATEGY NODE
# -----------------------------------------
def strategy_node(state: MarketState):
    trends = state["extracted_trends"]
    metrics = state["metrics"]
    competition = state["competitor_insights"]

    from agents.trend_agent import generate_strategy

    strategy = generate_strategy(trends, metrics, competition)

    return {
        "strategy": strategy
    }