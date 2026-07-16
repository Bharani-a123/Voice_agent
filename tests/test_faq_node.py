"""
test_faq_node.py — Tests the integrated faq_node using the real Qdrant vector database.
Verifies response relevance and correct formatting.

Run: python -m pytest tests/test_faq_node.py -v
"""

import pytest
import os
from dotenv import load_dotenv
from agent.nodes.faq import faq_node
from agent.state import initial_state

load_dotenv()

CLINIC_ID = "d72164a7-dd69-45c2-ac65-92c588b303a8"  # Greenfield seed


@pytest.mark.skipif("GROQ_API_KEY" not in os.environ, reason="Groq API key not set")
def test_faq_node_location():
    """Verify that asking location retrieves correct info."""
    state = initial_state(clinic_id=CLINIC_ID, call_sid="test-sid")
    state["current_input"] = "Where are you guys located?"

    res = faq_node(state)

    assert "response" in res
    assert "messages" in res
    response_text = res["response"].lower()
    
    # Check that location keywords are matched
    assert "mg road" in response_text or "bangalore" in response_text


@pytest.mark.skipif("GROQ_API_KEY" not in os.environ, reason="Groq API key not set")
def test_faq_node_insurance():
    """Verify that asking about insurance retrieves accepted companies."""
    state = initial_state(clinic_id=CLINIC_ID, call_sid="test-sid")
    state["current_input"] = "Do you accept Star Health or HDFC Ergo insurance?"

    res = faq_node(state)

    assert "response" in res
    response_text = res["response"].lower()
    
    assert "star health" in response_text or "hdfc ergo" in response_text or "lombard" in response_text


@pytest.mark.skipif("GROQ_API_KEY" not in os.environ, reason="Groq API key not set")
def test_faq_node_out_of_bounds():
    """Verify that out of bounds question yields the connect to staff fallback response."""
    state = initial_state(clinic_id=CLINIC_ID, call_sid="test-sid")
    state["current_input"] = "Can you recommend a recipe for chocolate cake?"

    res = faq_node(state)

    assert "response" in res
    response_text = res["response"].lower()
    
    # Check fallback phrasing
    assert "connect" in response_text or "staff" in response_text
