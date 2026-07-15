"""
test_schema.py — Phase 1 Test Gate
====================================
Validates that the database schema is correct and all constraints work.
Run AFTER seed.py.

Tests:
  1. Pilot clinic exists and is queryable
  2. RLS fail-closed: wrong clinic_id returns no rows
  3. Patients: PII is encrypted at rest (can decrypt correctly)
  4. Patients: phone_hash lookup works without decrypting
  5. Bookings: range exclusion blocks double-booking
  6. Bookings: cancelled booking does NOT block the same slot
  7. Cross-tenant isolation: different clinic_id can't see patients

Run: python db/test_schema.py
"""

import os
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

DB_URL          = os.environ["SUPABASE_DB_URL"]
APP_ENCRYPT_KEY = os.environ["APP_ENCRYPT_KEY"]
APP_HMAC_KEY    = os.environ["APP_HMAC_KEY"]
PILOT_CLINIC_ID = os.environ["PILOT_CLINIC_ID"]   # set after running seed.py


def make_phone_hash(phone: str) -> str:
    return hmac.new(
        APP_HMAC_KEY.encode(),
        phone.encode(),
        hashlib.sha256
    ).hexdigest()


def decrypt_value(conn, ciphertext: bytes) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pgp_sym_decrypt(%s::bytea, %s)",
            (ciphertext, APP_ENCRYPT_KEY)
        )
        return cur.fetchone()[0]


def set_clinic_session(conn, clinic_id: str):
    """Set the RLS session variable for the given clinic."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL app.current_clinic_id = %s", (str(clinic_id),))


PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  {status}  {name}" + (f"\n         → {detail}" if detail else ""))


def run_tests():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False  # required for SET LOCAL to work with RLS

    print("\n══════════════════════════════════════════════")
    print("  MediCare Connect — Phase 1 Schema Tests")
    print("══════════════════════════════════════════════\n")

    # ── Test 1: Pilot clinic exists ─────────────────────────────────────────
    print("Test 1: Pilot clinic exists")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        set_clinic_session(conn, PILOT_CLINIC_ID)
        cur.execute("SELECT id, name, status FROM clinics WHERE id = %s", (PILOT_CLINIC_ID,))
        clinic = cur.fetchone()
        check("Clinic row found",         clinic is not None)
        check("Clinic status = active",   clinic and clinic["status"] == "active",
              f"status={clinic['status'] if clinic else 'N/A'}")
    conn.rollback()

    # ── Test 2: RLS fail-closed ─────────────────────────────────────────────
    print("\nTest 2: RLS fail-closed (wrong clinic_id → no rows)")
    fake_clinic_id = str(uuid.uuid4())
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        set_clinic_session(conn, fake_clinic_id)
        cur.execute("SELECT COUNT(*) as cnt FROM patients")
        count = cur.fetchone()["cnt"]
        check("Wrong clinic_id returns 0 patients",  count == 0,
              f"returned {count} rows (expected 0)")
        cur.execute("SELECT COUNT(*) as cnt FROM bookings")
        count = cur.fetchone()["cnt"]
        check("Wrong clinic_id returns 0 bookings",  count == 0,
              f"returned {count} rows (expected 0)")
    conn.rollback()

    # ── Test 3: PII encryption + decryption ────────────────────────────────
    print("\nTest 3: Patient PII is encrypted at rest and decryptable")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        set_clinic_session(conn, PILOT_CLINIC_ID)
        cur.execute("SELECT name_enc, phone_enc, dob_enc FROM patients LIMIT 1")
        patient = cur.fetchone()

        name_dec  = decrypt_value(conn, patient["name_enc"])
        phone_dec = decrypt_value(conn, patient["phone_enc"])
        dob_dec   = decrypt_value(conn, patient["dob_enc"])

        check("name_enc is not plaintext",  "Ravi" not in str(patient["name_enc"]))
        check("Decrypted name is correct",  name_dec == "Ravi Kumar",
              f"got: {name_dec}")
        check("Decrypted phone is E.164",   phone_dec.startswith("+91"),
              f"got: {phone_dec}")
        check("Decrypted DOB is a date",    len(dob_dec) == 10,
              f"got: {dob_dec}")
    conn.rollback()

    # ── Test 4: phone_hash lookup ────────────────────────────────────────────
    print("\nTest 4: Identity lookup via phone_hash (no full-table decrypt)")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        set_clinic_session(conn, PILOT_CLINIC_ID)
        hash_val = make_phone_hash("+919876543210")
        cur.execute(
            "SELECT id FROM patients WHERE clinic_id = %s AND phone_hash = %s",
            (PILOT_CLINIC_ID, hash_val)
        )
        row = cur.fetchone()
        check("phone_hash lookup finds correct patient",  row is not None,
              f"hash={hash_val[:16]}...")

        # wrong number → no result
        wrong_hash = make_phone_hash("+910000000000")
        cur.execute(
            "SELECT id FROM patients WHERE clinic_id = %s AND phone_hash = %s",
            (PILOT_CLINIC_ID, wrong_hash)
        )
        row2 = cur.fetchone()
        check("Wrong phone hash finds nothing",  row2 is None)
    conn.rollback()

    # ── Test 5: Double-booking range exclusion ───────────────────────────────
    print("\nTest 5: Range exclusion constraint blocks overlapping bookings")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        set_clinic_session(conn, PILOT_CLINIC_ID)

        # Get pilot data
        cur.execute("SELECT id FROM doctors LIMIT 1")
        doctor_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM patients LIMIT 1")
        patient_id = cur.fetchone()["id"]

        base = datetime.now(tz=timezone.utc) + timedelta(days=2)
        slot_start = base.replace(hour=9, minute=0, second=0, microsecond=0)
        slot_end   = slot_start + timedelta(minutes=30)

        # Insert first booking
        cur.execute("""
            INSERT INTO bookings (clinic_id, patient_id, doctor_id, start_time, end_time, status)
            VALUES (%s, %s, %s, %s, %s, 'booked')
        """, (PILOT_CLINIC_ID, patient_id, doctor_id, slot_start, slot_end))

        # Try to insert overlapping booking (10 min into the same slot)
        overlap_start = slot_start + timedelta(minutes=10)
        overlap_end   = overlap_start + timedelta(minutes=30)
        blocked = False
        try:
            cur.execute("""
                INSERT INTO bookings (clinic_id, patient_id, doctor_id, start_time, end_time, status)
                VALUES (%s, %s, %s, %s, %s, 'booked')
            """, (PILOT_CLINIC_ID, patient_id, doctor_id, overlap_start, overlap_end))
        except psycopg2.errors.ExclusionViolation:
            blocked = True

        check("Overlapping slot is blocked by range exclusion",  blocked,
              "ExclusionViolation raised as expected")
    conn.rollback()  # clean up test bookings

    # ── Test 6: Cancelled booking doesn't block the same slot ───────────────
    print("\nTest 6: Cancelled booking does NOT block the same time slot")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        set_clinic_session(conn, PILOT_CLINIC_ID)

        cur.execute("SELECT id FROM doctors LIMIT 1")
        doctor_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM patients LIMIT 1")
        patient_id = cur.fetchone()["id"]

        base = datetime.now(tz=timezone.utc) + timedelta(days=3)
        slot_start = base.replace(hour=11, minute=0, second=0, microsecond=0)
        slot_end   = slot_start + timedelta(minutes=30)

        # Insert cancelled booking
        cur.execute("""
            INSERT INTO bookings (clinic_id, patient_id, doctor_id, start_time, end_time, status)
            VALUES (%s, %s, %s, %s, %s, 'cancelled')
        """, (PILOT_CLINIC_ID, patient_id, doctor_id, slot_start, slot_end))

        # Same slot should now be bookable
        blocked = False
        try:
            cur.execute("""
                INSERT INTO bookings (clinic_id, patient_id, doctor_id, start_time, end_time, status)
                VALUES (%s, %s, %s, %s, %s, 'booked')
            """, (PILOT_CLINIC_ID, patient_id, doctor_id, slot_start, slot_end))
        except psycopg2.errors.ExclusionViolation:
            blocked = True

        check("Cancelled booking allows same slot to be rebooked",  not blocked,
              "No ExclusionViolation — slot is available again")
    conn.rollback()

    # ── Test 7: Departments and doctors seeded correctly ────────────────────
    print("\nTest 7: Departments and doctors seeded correctly")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        set_clinic_session(conn, PILOT_CLINIC_ID)
        cur.execute("SELECT COUNT(*) as cnt FROM departments WHERE clinic_id = %s", (PILOT_CLINIC_ID,))
        dept_count = cur.fetchone()["cnt"]
        check("2 departments seeded",  dept_count == 2, f"found {dept_count}")

        cur.execute("SELECT COUNT(*) as cnt FROM doctors WHERE clinic_id = %s AND active = TRUE", (PILOT_CLINIC_ID,))
        doc_count = cur.fetchone()["cnt"]
        check("3 active doctors seeded",  doc_count == 3, f"found {doc_count}")
    conn.rollback()

    # ── Summary ──────────────────────────────────────────────────────────────
    conn.close()
    passed = sum(1 for r in results if r[0] == PASS)
    total  = len(results)
    print(f"\n══════════════════════════════════════════════")
    print(f"  Results: {passed}/{total} passed")
    if passed == total:
        print("  🎉 Phase 1 test gate PASSED — ready for Phase 2!")
    else:
        print("  ⚠️  Some tests failed. Fix before moving to Phase 2.")
    print("══════════════════════════════════════════════\n")


if __name__ == "__main__":
    run_tests()
