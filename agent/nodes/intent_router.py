"""
intent_router_node — Classifies the caller's intent using Groq/Llama.
Intents: book | reschedule | cancel | faq | unclear

This node runs when current_intent is None (start of call or after
a completed flow). It does NOT generate a user-facing response — 
it just classifies and routes. The routed-to node generates the response.
"""

import os
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from agent.state import CallState
from agent.mock_data import get_departments_text, get_doctors_text

SYSTEM_PROMPT = """You are the AI intent classifier for {clinic_name}.

The clinic has these departments: {departments}
And these doctors: {doctors}

Classify the caller's message into EXACTLY one intent:
- BOOK: wants to book a NEW appointment
- RESCHEDULE: wants to change/move an EXISTING appointment
- CANCEL: wants to cancel an EXISTING appointment
- FAQ: asking about hours, location, insurance, doctors, services, first visit, etc.
- UNCLEAR: cannot determine what they want

Reply in this EXACT format (no extra text):
INTENT: <BOOK|RESCHEDULE|CANCEL|FAQ|UNCLEAR>"""


def intent_router_node(state: CallState) -> dict:
    """Classifies intent. The routing function (not this node) generates the first response."""
    try:
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0,
            max_tokens=20,
            groq_api_key=os.environ["GROQ_API_KEY"],
        )

        system = SYSTEM_PROMPT.format(
            clinic_name="Greenfield Multi-Specialty Clinic",
            departments=get_departments_text(),
            doctors=get_doctors_text(),
        )

        # Include recent history for context
        history_lines = []
        for msg in state.get("messages", [])[-4:]:
            role = "Caller" if msg.type == "human" else "Receptionist"
            history_lines.append(f"{role}: {msg.content}")

        context = "\n".join(history_lines)
        user_content = f"{context}\nCaller: {state['current_input']}" if context else state['current_input']

        response = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=user_content),
        ])

        content = response.content.strip().upper()
        intent = "unclear"
        for line in content.split("\n"):
            if line.startswith("INTENT:"):
                raw = line.replace("INTENT:", "").strip().lower()
                if raw in ("book", "reschedule", "cancel", "faq", "unclear"):
                    intent = raw
                    break

        # Reset retries if we got a clear intent
        retries = state.get("intent_retries", 0)
        if intent == "unclear":
            retries += 1
        else:
            retries = 0

        return {
            "current_intent": intent,
            "intent_retries": retries,
        }

    except Exception as e:
        return {
            "current_intent": "unclear",
            "intent_retries": state.get("intent_retries", 0) + 1,
        }
