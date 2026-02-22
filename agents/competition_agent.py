# Competition analysis agent

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
# Competition Analysis
# -----------------------------
def analyze_competition(marketplace_data: List[Dict]) -> Dict:
    """
    Analyze marketplace data to extract:
    - Competition score (0-100)
    - Competitive insights
    """

    prompt = f"""
You are a competitive market analyst.

Analyze the following marketplace data:

{marketplace_data}

Tasks:
1. Estimate competition intensity (0-100).
2. Identify pricing patterns.
3. Identify saturation signals (high review count, low differentiation).

Return ONLY valid JSON in this format:

{{
  "competition_score": 60,
  "insights": ["insight1", "insight2"]
}}

Do NOT include explanations.
Return ONLY JSON.
"""

    response = llm.invoke([HumanMessage(content=prompt)])
    parsed = safe_json_parse(response.content)

    return {
        "competition_score": parsed.get("competition_score", 0),
        "insights": parsed.get("insights", [])
    }
