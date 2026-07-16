"""
test_server.py — Unit tests for FastAPI voice server endpoints (Phase 5).
Verifies TwiML generation and LLM brain simulator endpoint.

Run: python -m pytest tests/test_server.py -v
"""

import pytest
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient
from main import app
from agent.rag_service import rag
from db.ingest_faq import FAQ_DATA

CLINIC_ID = "d72164a7-dd69-45c2-ac65-92c588b303a8"
client = TestClient(app)


@pytest.fixture(autouse=True, scope="module")
def seed_test_database():
    """Seeds the in-memory Qdrant instance with default FAQ data for testing."""
    rag.ingest_faq_text(CLINIC_ID, "test_doc", FAQ_DATA)


def test_incoming_call_twiml():
    """Verify that incoming-call returns valid Twilio TwiML XML."""
    resp = client.post("/incoming-call", data={"CallSid": "test-call-123"})
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]

    # Parse XML and verify structure
    root = ET.fromstring(resp.text)
    assert root.tag == "Response"
    
    # Check for Connect and Stream elements
    connect_elem = root.find("Connect")
    assert connect_elem is not None
    stream_elem = connect_elem.find("Stream")
    assert stream_elem is not None
    assert "media-stream" in stream_elem.get("url")


def test_simulate_turn():
    """Verify that simulate-turn triggers receptionist brain and updates state."""
    payload = {
        "text": "Do you accept Star Health insurance?",
        "state": {
            "clinic_id": "d72164a7-dd69-45c2-ac65-92c588b303a8",
            "call_sid": "test-sim-123",
            "messages": [],
            "current_input": "",
            "response": ""
        }
    }
    resp = client.post("/simulate-turn", json=payload)
    assert resp.status_code == 200
    
    data = resp.json()
    assert "response" in data
    assert "state" in data
    
    response_text = data["response"].lower()
    # Check that it answered correctly using Qdrant FAQ context
    assert "star health" in response_text or "lombard" in response_text or "insurance" in response_text
