"""
escalate_node — Terminal node. Live-transfers the call to the clinic's human nurse/staff.
In Phase 2 (text-only): simulates the transfer with a message.
In Phase 6: triggers a real Twilio live call transfer.
"""

from langchain_core.messages import AIMessage
from agent.state import CallState
from agent.mock_data import PILOT_CLINIC


def escalate_node(state: CallState) -> dict:
    """
    Immediately ends AI involvement and transfers to a human.
    Logs escalated=True. Never stores symptom text — only the rule name.
    """
    escalation_number = PILOT_CLINIC["escalation_phone"]

    response = (
        "I'm connecting you to one of our medical staff right now. "
        "Please hold for just a moment."
    )

    # In Phase 6, this is where Twilio live transfer fires:
    # twilio_client.calls(call_sid).update(method="POST", url=transfer_twiml_url)
    print(f"\n  [ESCALATION] Transferring to {escalation_number}")
    print(f"  [ESCALATION] Rule triggered: {state.get('matched_rule', 'unknown')}")
    print(f"  [NOTE] In Phase 6, Twilio live transfer fires here.")

    return {
        "escalated": True,
        "call_ended": True,
        "outcome": "escalated",
        "response": response,
        "messages": [AIMessage(content=response)],
    }
