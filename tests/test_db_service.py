"""
test_db_service.py — Integration tests for db_service.py.
Verifies that RLS context setting, queries, encryption, and hash lookups work.

Before running:
- Connect to mobile data hotspot or Cloudflare WARP so outbound port 5432 is open.

Run: python -m pytest tests/test_db_service.py -v
"""

import pytest
import uuid
from agent.db_service import DBService

CLINIC_ID = "d72164a7-dd69-45c2-ac65-92c588b303a8"  # matches our seed
TEST_PHONE = "+919999888877"
TEST_NAME = "Test Patient"
TEST_DOB = "1990-01-01"


@pytest.fixture(scope="module")
def db_service():
    return DBService()


def test_get_departments(db_service):
    depts = db_service.get_departments(CLINIC_ID)
    assert len(depts) >= 2
    names = [d["name"] for d in depts]
    assert "Cardiology" in names
    assert "Orthopaedics" in names


def test_get_doctors(db_service):
    docs = db_service.get_doctors(CLINIC_ID)
    assert len(docs) >= 3
    names = [d["name"] for d in docs]
    assert "Dr. Priya Sharma" in names


def test_patient_encryption_cycle(db_service):
    """
    1. Create a patient (PII is encrypted)
    2. Lookup patient by phone hash
    3. Verify decrypted details match
    """
    # Create test patient
    pat_id = db_service.create_patient(CLINIC_ID, TEST_NAME, TEST_PHONE, TEST_DOB)
    assert pat_id is not None
    assert isinstance(pat_id, str)

    # Find patient by phone
    patient = db_service.find_patient_by_phone(CLINIC_ID, TEST_PHONE)
    assert patient is not None
    assert patient["id"] == pat_id
    assert patient["name"] == TEST_NAME
    assert patient["phone"] == TEST_PHONE
    assert patient["dob"] == TEST_DOB

    # Clean up test patient record
    import psycopg2
    from agent.db_service import DB_URL
    conn = psycopg2.connect(DB_URL)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM patients WHERE id = %s", (pat_id,))
    conn.commit()
    conn.close()


def test_rls_isolation_blocking(db_service):
    """Verify that using an invalid/random clinic_id returns no records (RLS enforcement)."""
    fake_clinic_id = str(uuid.uuid4())
    depts = db_service.get_departments(fake_clinic_id)
    assert len(depts) == 0  # blocked by RLS policy!
