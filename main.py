# Main entry point
import time
from graph.workflow import build_workflow
from graph.state import MarketState


def run_market_analysis():
    # ----------------------------------------
    # 1️⃣ Initial Artisan Profile Input
    # ----------------------------------------
    initial_state: MarketState = {
        "artisan_profile": {
            "artisan_type": "Terracotta Pottery",
            "location": "India",
            "budget_level": "Low",
            "production_capacity": 100,
            "target_market": None
        },

        # Raw Data
        "search_results": [],
        "marketplace_data": [],

        # Processed Intelligence
        "extracted_trends": [],
        "competitor_insights": [],

        # Metrics
        "metrics": {},

        # Final Strategy
        "strategy": None,

        # System Metadata
        "system": {
            "execution_time": None,
            "model_used": "llama3.1:8b",
            "version": "v1.0",
            "errors": []
        }
    }

    # ----------------------------------------
    # 2️⃣ Build Workflow
    # ----------------------------------------
    app = build_workflow()

    # Optional: Visualize graph
    try:
        app.get_graph().draw_png("workflow.png")
        print("Workflow graph saved as workflow.png")
    except:
        pass

    # ----------------------------------------
    # 3️⃣ Execute Workflow
    # ----------------------------------------
    start_time = time.time()

    final_state = app.invoke(initial_state)

    end_time = time.time()
    execution_time = round(end_time - start_time, 2)

    final_state["system"]["execution_time"] = execution_time

    # ----------------------------------------
    # 4️⃣ Display Results
    # ----------------------------------------
    print("\n==============================")
    print("📊 MARKET INTELLIGENCE REPORT")
    print("==============================\n")

    print("🔎 Extracted Trends:")
    print(final_state.get("extracted_trends", []))

    print("\n📈 Metrics:")
    print(final_state.get("metrics", {}))

    print("\n🧠 Strategy:")
    print(final_state.get("strategy", {}))

    print("\n⏱ Execution Time:", execution_time, "seconds")
    print("\n==============================\n")


if __name__ == "__main__":
    run_market_analysis()