"""
faq_node — Answers clinic FAQ questions.
Phase 2: Uses keyword matching against mock FAQ content.
Phase 4: Replaced by RAG against Qdrant vector store.
"""

import os
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from agent.state import CallState
from agent.mock_data import FAQ_CONTENT, PILOT_CLINIC

FAQ_SYSTEM = """You are a helpful AI receptionist for {clinic_name}.
Answer the caller's question using ONLY the information provided below.
If the answer isn't in the provided information, say you'll connect them with staff.
Keep your answer concise — this is a phone call. 1-3 sentences maximum.
Never give medical advice. Never diagnose symptoms.

Clinic Information:
{faq_content}
"""

def faq_node(state: CallState) -> dict:
    """Answers FAQ questions using structured clinic data + LLM synthesis."""
    text = state.get("current_input", "")

    try:
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.1,
            max_tokens=150,
            groq_api_key=os.environ["GROQ_API_KEY"],
        )

        faq_text = "\n".join(f"- {k}: {v}" for k, v in FAQ_CONTENT.items())

        response_obj = llm.invoke([
            SystemMessage(content=FAQ_SYSTEM.format(
                clinic_name=PILOT_CLINIC["name"],
                faq_content=faq_text,
            )),
            HumanMessage(content=text),
        ])

        answer = response_obj.content.strip()

        # Add follow-up prompt
        full_response = f"{answer} Is there anything else I can help you with?"

    except Exception:
        full_response = (
            "I'm sorry, I don't have that information available right now. "
            "Let me connect you with a staff member who can help. "
            "Is there anything else I can assist you with?"
        )

    return {
        "current_intent": None,  # reset so caller can ask another question
        "outcome":        "faq_answered",
        "response":       full_response,
        "messages":       [AIMessage(content=full_response)],
    }
