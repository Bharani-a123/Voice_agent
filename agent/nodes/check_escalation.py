"""
check_escalation node — ALWAYS runs first on every turn.
If escalation is detected, sets escalated=True and short-circuits
the entire graph to the escalate_node regardless of what else is active.
This is the safety-critical preemption mechanism.
"""

from langchain_core.messages import HumanMessage
from agent.state import CallState
from agent.escalation import detector


def check_escalation_node(state: CallState) -> dict:
    """
    Runs the two-layer escalation check on the current user input.
    If triggered, sets escalated=True and matched_rule.
    The graph's conditional edge then routes to escalate_node immediately.
    """
    text = state.get("current_input", "")
    result = detector.check(text)

    # Always append user message to history
    updates: dict = {
        "messages": [HumanMessage(content=text)],
    }

    if result["escalate"]:
        updates["escalated"] = True
        updates["matched_rule"] = result["matched_rule"]

    return updates
