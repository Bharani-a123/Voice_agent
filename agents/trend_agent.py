# Trend analysis agent
import json
from typing import List, Dict

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage


# -----------------------------
# Initialize Ollama Model
# -----------------------------
llm = ChatOllama(
    model="llama3.1:8b",
    temperature=0,
    num_ctx=4096
)


# -----------------------------
# Safe JSON Parsing
# -----------------------------
def safe_json_parse(text: str) -> Dict:
    try:
        return json.loads(text)
    except:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end])
            except:
                pass
        return {}


# -----------------------------
# Trend Analysis Function
# -----------------------------
def analyze_trends(search_results: List[Dict]) -> Dict:
    """
    Analyze search results to extract:
    - Top trends
    - Trend momentum score (0-100)
    """

    prompt = f"""
You are a professional market intelligence analyst.

Analyze the following search results:

{search_results}

Tasks:
1. Identify top 5 emerging product trends.
2. Estimate demand momentum score (0-100).
3. Return ONLY valid JSON in this format:

{{
  "trends": ["trend1", "trend2"],
  "momentum_score": 75
}}

Do NOT include explanations.
Do NOT include markdown.
Return ONLY JSON.
"""

    response = llm.invoke([HumanMessage(content=prompt)])
    parsed = safe_json_parse(response.content)

    return {
        "trends": parsed.get("trends", []),
        "momentum_score": parsed.get("momentum_score", 0)
    }


# -----------------------------
# Strategy Generator
# -----------------------------
def generate_strategy(trends: List[str], metrics: Dict, competition_insights: List[str]) -> Dict:
    """
    Generate final strategic recommendations.
    """

    prompt = f"""
You are a strategic advisor helping Indian artisans.

Trends:
{trends}

Metrics:
{metrics}

Competition Insights:
{competition_insights}

Generate:
- 3 recommended product ideas
- Suggested pricing logic
- Short strategic summary
- Confidence score (0-1)

Return ONLY valid JSON in this format:

{{
  "recommended_products": [
    {{"name": "", "reason": ""}}
  ],
  "summary": "",
  "confidence_score": 0.85
}}

Do NOT include explanations.
Return ONLY JSON.
"""

    response = llm.invoke([HumanMessage(content=prompt)])
    parsed = safe_json_parse(response.content)

    return {
        "recommended_products": parsed.get("recommended_products", []),
        "summary": parsed.get("summary", ""),
        "confidence_score": parsed.get("confidence_score", 0.0)
    }