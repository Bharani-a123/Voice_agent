"""
unclear_node — Handles when the system can't determine the caller's intent.
Max 2 retries before escalating to a human (prevents infinite loop).
"""

from langchain_core.messages import AIMessage
from agent.state import CallState


REPROMPT_MESSAGES = [
    (
        "I'm sorry, I didn't quite catch that. "
        "I can help you with booking a new appointment, rescheduling or cancelling "
        "an existing one, or answering questions about our clinic. "
        "Which of these can I help you with?"
    ),
    (
        "I'm still having a little trouble understanding. "
        "Just to confirm — are you looking to book an appointment, "
        "make changes to an existing booking, or do you have a question about our clinic?"
    ),
]


def unclear_node(state: CallState) -> dict:
    """
    Re-prompts the caller to clarify. After 2 retries, escalates.
    The graph's conditional edge handles routing to escalate_node
    when intent_retries >= 2.
    """
    retries = state.get("intent_retries", 0)

    if retries >= 2:
        # Graph will route to escalate_node — this response is the handoff message
        response = (
            "I'm having difficulty understanding your request. "
            "Let me connect you with one of our staff members "
            "who will be happy to assist you."
        )
    else:
        # Pick the appropriate reprompt message
        idx = min(retries, len(REPROMPT_MESSAGES) - 1)
        response = REPROMPT_MESSAGES[idx]

    return {
        "response": response,
        "messages": [AIMessage(content=response)],
    }
