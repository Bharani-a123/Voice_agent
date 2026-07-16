"""
test_rag.py — Unit tests for local Qdrant RAG service.
Verifies embedding generation, search relevance, and multi-tenant isolation.

Run: python -m pytest tests/test_rag.py -v
"""

import pytest
import uuid
from agent.rag_service import rag

TEST_CLINIC = "d72164a7-dd69-45c2-ac65-92c588b303a8"  # Greenfield
FAKE_CLINIC = str(uuid.uuid4())


@pytest.fixture(scope="module")
def rag_service():
    return rag


def test_rag_ingest_and_query(rag_service):
    """Test standard ingestion and matching query retrieval."""
    test_faq = "Clinic X specializes in Neurology. Dr. Sandra Vance heads the department."

    # Ingest text
    rag_service.ingest_faq_text(TEST_CLINIC, "test_doc", test_faq)

    # Query with relevant search
    results = rag_service.query(TEST_CLINIC, "who leads neurology?", limit=1)
    assert len(results) >= 1
    assert "Sandra Vance" in results[0]


def test_rag_multi_tenant_isolation(rag_service):
    """
    Ensure that a query from a different clinic_id returns no results,
    verifying strict tenant boundaries.
    """
    # Query neurologists using a different/fake clinic ID
    results = rag_service.query(FAKE_CLINIC, "neurology doctors")
    assert len(results) == 0  # must be isolated and return nothing!
