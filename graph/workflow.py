# Workflow definitions

from langgraph.graph import StateGraph, END
from graph.state import MarketState
from graph.nodes import (
    search_node,
    marketplace_node,
    trend_analysis_node,
    competition_analysis_node,
    scoring_node,
    strategy_node,
)


def build_workflow():
    workflow = StateGraph(MarketState)

    # Add nodes
    workflow.add_node("search", search_node)
    workflow.add_node("marketplace", marketplace_node)
    workflow.add_node("trend_analysis", trend_analysis_node)
    workflow.add_node("competition_analysis", competition_analysis_node)
    workflow.add_node("scoring", scoring_node)
    workflow.add_node("strategy", strategy_node)

    # Define execution flow
    workflow.set_entry_point("search")

    workflow.add_edge("search", "marketplace")
    workflow.add_edge("marketplace", "trend_analysis")
    workflow.add_edge("trend_analysis", "competition_analysis")
    workflow.add_edge("competition_analysis", "scoring")
    workflow.add_edge("scoring", "strategy")
    workflow.add_edge("strategy", END)

    return workflow.compile()