"""
seed.py — Phase 1 Database Seed Script
=======================================
Seeds one pilot clinic with:
  - 1 clinic (Greenfield Multi-Specialty Clinic)
  - 2 departments (Cardiology, Orthopaedics)
  - 3 doctors (2 in Cardiology, 1 in Ortho)
  - 2 sample patients (PII encrypted)
  - 2 sample bookings (one active, one cancelled)
  - 1 call log entry
  - 1 FAQ document record

Run: python db/seed.py
Requires: .env file with SUPABASE_DB_URL and APP_SECRET_KEY set
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

# ── Config ──────────────────────────────────────────────────────────────────
DB_URL = os.environ["SUPABASE_DB_URL"]
# This key encrypts PII columns. Must be long, random, never committed to git.
# Use a DIFFERENT key for HMAC (phone_hash) vs encryption (name_enc, phone_enc, dob_enc).
APP_ENCRYPT_KEY = os.environ["APP_ENCRYPT_KEY"]
APP_HMAC_KEY = os.environ["APP_HMAC_KEY"]


# ── Helpers ──────────────────────────────────────────────────────────────────
def make_phone_hash(phone: str) -> str:
    """
    HMAC-SHA256 of a phone number using APP_HMAC_KEY.
    Deterministic for indexed lookup, not reversible.
    Use E.164 format consistently: '+911234567890'
    """
    return hmac.new(
        key=APP_HMAC_KEY.encode(),
        msg=phone.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()


def encrypt_value(conn, plaintext: str) -> bytes:
    """
    Encrypt a plaintext string using pgcrypto pgp_sym_encrypt.
    Returns the encrypted bytes to store in a BYTEA column.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pgp_sym_encrypt(%s, %s)",
            (plaintext, APP_ENCRYPT_KEY)
        )
        return cur.fetchone()[0]


def decrypt_value(conn, ciphertext: bytes) -> str:
    """
    Decrypt a BYTEA ciphertext using pgcrypto pgp_sym_decrypt.
    Used only for verification in this seed script.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pgp_sym_decrypt(%s::bytea, %s)",
            (ciphertext, APP_ENCRYPT_KEY)
        )
        return cur.fetchone()[0]


# ── Seed ─────────────────────────────────────────────────────────────────────
def seed():
    print("Connecting to Supabase Postgres...")
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # ── Step 1: Clinic ──────────────────────────────────────────────
            print("\n[1/7] Creating pilot clinic...")
            cur.execute("""
                INSERT INTO clinics (name, timezone, escalation_phone_e164, calendar_provider, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name
            """, (
                "Greenfield Multi-Specialty Clinic",
                "Asia/Kolkata",
                "+911800123456",   # pilot clinic's nurse/staff number
                "google",
                "active"
            ))
            clinic = cur.fetchone()
            clinic_id = clinic["id"]
            print(f"   ✓ Clinic created: {clinic['name']} (id={clinic_id})")

            # ── Step 2: Departments ─────────────────────────────────────────
            print("\n[2/7] Creating departments...")
            cur.execute("""
                INSERT INTO departments (clinic_id, name) VALUES
                    (%s, 'Cardiology'),
                    (%s, 'Orthopaedics')
                RETURNING id, name
            """, (clinic_id, clinic_id))
            departments = cur.fetchall()
            dept_map = {d["name"]: d["id"] for d in departments}
            for d in departments:
                print(f"   ✓ Department: {d['name']} (id={d['id']})")

            # ── Step 3: Doctors ─────────────────────────────────────────────
            print("\n[3/7] Creating doctors...")
            doctors_data = [
                ("Dr. Priya Sharma",   "Cardiology",    "cal_resource_priya_sharma@greenfield.clinic"),
                ("Dr. Arjun Mehta",    "Cardiology",    "cal_resource_arjun_mehta@greenfield.clinic"),
                ("Dr. Kavitha Rajan",  "Orthopaedics",  "cal_resource_kavitha_rajan@greenfield.clinic"),
            ]
            doctor_map = {}
            for name, dept_name, cal_id in doctors_data:
                cur.execute("""
                    INSERT INTO doctors (clinic_id, department_id, name, calendar_id, active)
                    VALUES (%s, %s, %s, %s, TRUE)
                    RETURNING id, name
                """, (clinic_id, dept_map[dept_name], name, cal_id))
                doc = cur.fetchone()
                doctor_map[name] = doc["id"]
                print(f"   ✓ Doctor: {doc['name']} (id={doc['id']})")

            # ── Step 4: Patients (PII encrypted) ────────────────────────────
            print("\n[4/7] Creating patients (encrypting PII)...")
            patients_data = [
                ("Ravi Kumar",  "+919876543210", "1985-03-15"),
                ("Sunita Patel", "+919123456789", "1972-08-22"),
            ]
            patient_ids = []
            for name, phone, dob in patients_data:
                name_enc  = encrypt_value(conn, name)
                phone_enc = encrypt_value(conn, phone)
                dob_enc   = encrypt_value(conn, dob)
                phone_hash = make_phone_hash(phone)

                cur.execute("""
                    INSERT INTO patients (clinic_id, name_enc, phone_enc, dob_enc, phone_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (clinic_id, name_enc, phone_enc, dob_enc, phone_hash))
                pid = cur.fetchone()["id"]
                patient_ids.append(pid)
                print(f"   ✓ Patient: {name} (id={pid}) — PII encrypted, phone_hash={phone_hash[:16]}...")

            # ── Step 5: Bookings ────────────────────────────────────────────
            print("\n[5/7] Creating sample bookings...")
            now = datetime.now(tz=timezone.utc)
            tomorrow_10am = (now + timedelta(days=1)).replace(hour=4, minute=30, second=0, microsecond=0)  # 10:00 IST = 04:30 UTC
            tomorrow_1030 = tomorrow_10am + timedelta(minutes=30)

            # Booking 1: active booking (Ravi → Dr. Priya Sharma)
            cur.execute("""
                INSERT INTO bookings
                    (clinic_id, patient_id, doctor_id, start_time, end_time, status, ext_event_id)
                VALUES (%s, %s, %s, %s, %s, 'booked', %s)
                RETURNING id
            """, (
                clinic_id,
                patient_ids[0],
                doctor_map["Dr. Priya Sharma"],
                tomorrow_10am,
                tomorrow_1030,
                "google_event_seed_001"
            ))
            b1 = cur.fetchone()["id"]
            print(f"   ✓ Booking 1 (active): Ravi → Dr. Priya Sharma @ 10:00 AM tomorrow (id={b1})")

            # Booking 2: cancelled booking (Sunita → Dr. Arjun Mehta)
            next_week_2pm = (now + timedelta(days=7)).replace(hour=8, minute=30, second=0, microsecond=0)  # 14:00 IST
            cur.execute("""
                INSERT INTO bookings
                    (clinic_id, patient_id, doctor_id, start_time, end_time, status, ext_event_id)
                VALUES (%s, %s, %s, %s, %s, 'cancelled', %s)
                RETURNING id
            """, (
                clinic_id,
                patient_ids[1],
                doctor_map["Dr. Arjun Mehta"],
                next_week_2pm,
                next_week_2pm + timedelta(minutes=30),
                "google_event_seed_002"
            ))
            b2 = cur.fetchone()["id"]
            print(f"   ✓ Booking 2 (cancelled): Sunita → Dr. Arjun Mehta (id={b2})")

            # ── Step 6: Call log ────────────────────────────────────────────
            print("\n[6/7] Creating sample call log...")
            cur.execute("""
                INSERT INTO call_logs
                    (clinic_id, call_sid, escalated, outcome, latency_ms_p50, turn_count, started_at, ended_at)
                VALUES (%s, %s, FALSE, 'booked', 1240, 5, %s, %s)
                RETURNING id
            """, (
                clinic_id,
                "CA_seed_test_001",
                now - timedelta(hours=2),
                now - timedelta(hours=2) + timedelta(minutes=3)
            ))
            log_id = cur.fetchone()["id"]
            print(f"   ✓ Call log: outcome=booked, latency=1240ms, turns=5 (id={log_id})")

            # ── Step 7: FAQ document record ─────────────────────────────────
            print("\n[7/7] Creating FAQ document record...")
            cur.execute("""
                INSERT INTO faq_documents (clinic_id, source_name, qdrant_ids, indexed_at)
                VALUES (%s, %s, %s, NULL)
                RETURNING id
            """, (
                clinic_id,
                "greenfield_clinic_faq_v1.pdf",
                "{}"   # empty until Phase 4 (RAG) indexes it into Qdrant
            ))
            faq_id = cur.fetchone()["id"]
            print(f"   ✓ FAQ document registered: greenfield_clinic_faq_v1.pdf (id={faq_id}) — will be indexed in Phase 4")

        # ── Commit ────────────────────────────────────────────────────────────
        conn.commit()
        print("\n✅ Seed complete! Pilot clinic is ready.")
        print(f"   Clinic ID (save this): {clinic_id}")
        print("   Add it to your .env as: PILOT_CLINIC_ID=" + str(clinic_id))

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Seed failed, rolled back. Error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
