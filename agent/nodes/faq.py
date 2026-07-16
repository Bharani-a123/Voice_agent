"""
faq_node — Answers clinic FAQ questions.
Phase 4: Replaced mock FAQ with RAG against Qdrant vector store.
"""

import os
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from agent.state import CallState
from agent.db_service import db
from agent.rag_service import rag

FAQ_SYSTEM = """You are a helpful AI receptionist for {clinic_name}.
Answer the caller's question using ONLY the provided clinic information below.
If the answer isn't in the provided information, say you'll connect them with a staff member.
Keep your answer concise — this is a phone call. 1-3 sentences maximum.
Never give medical advice. Never diagnose symptoms.

Clinic Information:
{faq_content}
"""

def faq_node(state: CallState) -> dict:
    """Answers FAQ questions using Qdrant vector store RAG + LLM synthesis."""
    text = state.get("current_input", "")
    clinic_id = state.get("clinic_id")

    try:
        # 1. Fetch clinic details dynamically
        clinic = db.get_clinic(clinic_id)
        clinic_name = clinic["name"] if clinic else "the clinic"

        # 2. Query Qdrant for matching passages
        passages = rag.query(clinic_id, text, limit=2)
        faq_text = "\n\n".join(passages) if passages else "No information available."

        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.1,
            max_tokens=150,
            groq_api_key=os.environ["GROQ_API_KEY"],
        )

        response_obj = llm.invoke([
            SystemMessage(content=FAQ_SYSTEM.format(
                clinic_name=clinic_name,
                faq_content=faq_text,
            )),
            HumanMessage(content=text),
        ])

        answer = response_obj.content.strip()

        # Add follow-up prompt
        full_response = f"{answer} Is there anything else I can help you with?"

    except Exception as e:
        print(f"[FAQ Node] Error in RAG/LLM lookup: {e}")
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

