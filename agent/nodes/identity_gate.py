"""
identity_gate_node — Verifies caller identity before allowing reschedule/cancel.
Asks for name + phone number. Checks against patient records.
Max 2 retries before escalating to a human.
"""

import os
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from agent.state import CallState
from agent.mock_data import verify_patient_identity

EXTRACT_PROMPT = """Extract the caller's name and phone number from their message.
Reply in EXACT format:
NAME: <full name or NONE>
PHONE: <phone number with country code or NONE>

Caller said: "{text}"
"""

def identity_gate_node(state: CallState) -> dict:
    """
    Extracts name+phone from caller's message and verifies identity.
    - If verified: sets identity_verified=True, patient_id, patient_name
    - If not verified + retries < 2: asks again politely
    - If not verified + retries >= 2: escalates
    """
    retries = state.get("identity_retries", 0)
    text    = state.get("current_input", "")

    # First call to this node: ask for credentials
    if not text.strip() or (not any(c.isdigit() for c in text) and len(text.split()) < 3):
        response = (
            "To access your existing appointment, I'll need to verify your identity. "
            "Could you please provide your full name and registered phone number?"
        )
        return {
            "response": response,
            "messages": [AIMessage(content=response)],
        }

    # Try to extract name + phone via LLM
    try:
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0,
            max_tokens=50,
            groq_api_key=os.environ["GROQ_API_KEY"],
        )
        resp = llm.invoke([HumanMessage(content=EXTRACT_PROMPT.format(text=text))])
        content = resp.content.strip()

        name  = "NONE"
        phone = "NONE"
        for line in content.split("\n"):
            if line.startswith("NAME:"):
                name = line.replace("NAME:", "").strip()
            elif line.startswith("PHONE:"):
                phone = line.replace("PHONE:", "").strip()

    except Exception:
        name  = text  # fallback: use raw text
        phone = text

    # Verify against patient records
    if name != "NONE" and phone != "NONE":
        result = verify_patient_identity(name, phone)
        if result["verified"]:
            response = (
                f"Thank you, {result['patient_name']}. I've verified your identity. "
                "Let me pull up your appointment now."
            )
            return {
                "identity_verified": True,
                "patient_id":        result["patient_id"],
                "patient_name":      result["patient_name"],
                "identity_retries":  0,
                "response":          response,
                "messages":          [AIMessage(content=response)],
            }

    # Verification failed
    retries += 1
    if retries >= 2:
        response = (
            "I'm having trouble verifying your identity. "
            "Let me connect you with a staff member who can assist you directly."
        )
        return {
            "identity_retries": retries,
            "response":         response,
            "messages":         [AIMessage(content=response)],
            # graph will route to escalate_node based on retries >= 2
        }

    response = (
        "I'm sorry, I couldn't verify that information. "
        "Could you please provide your full name and the phone number "
        "registered with us?"
    )
    return {
        "identity_retries": retries,
        "response":         response,
        "messages":         [AIMessage(content=response)],
    }
