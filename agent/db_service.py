"""
db_service.py — Supabase Postgres integration.
Handles all read and write queries for clinics, doctors, departments, patients, and bookings.
Uses client-side pgcrypto encryption via SQL to protect patient PII.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Global variables for keys
ENC_KEY  = os.environ.get("APP_ENCRYPT_KEY")
HMAC_KEY = os.environ.get("APP_HMAC_KEY")
DB_URL   = os.environ.get("SUPABASE_DB_URL")


class DBService:
    """Manages raw SQL database operations via psycopg2 with safety-first paradigms."""

    def __init__(self):
        self.db_url = DB_URL
        self.enc_key = ENC_KEY
        self.hmac_key = HMAC_KEY

        if not self.db_url:
            raise ValueError("SUPABASE_DB_URL is missing in environment variables.")
        if not self.enc_key or len(self.enc_key) < 32:
            raise ValueError("APP_ENCRYPT_KEY must be a valid 64-character hex key.")
        if not self.hmac_key or len(self.hmac_key) < 32:
            raise ValueError("APP_HMAC_KEY must be a valid 64-character hex key.")

    def _get_conn(self, clinic_id: str = None):
        """
        Returns a new connection.
        If clinic_id is provided, sets the session variable 'app.current_clinic_id'
        so Row-Level Security (RLS) policies are automatically enforced.
        """
        conn = psycopg2.connect(self.db_url)
        if clinic_id:
            # Set the RLS session context immediately
            with conn.cursor() as cur:
                cur.execute("SET LOCAL app.current_clinic_id = %s", (clinic_id,))
        return conn

    def get_clinic_timezone(self, clinic_id: str) -> str:
        """Fetch clinic timezone, defaults to UTC if not found."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT timezone FROM clinics WHERE id = %s", (clinic_id,))
                    row = cur.fetchone()
                    return row["timezone"] if row else "UTC"
        except Exception as e:
            print(f"[DB] Error getting timezone: {e}")
            return "UTC"

    def get_departments(self, clinic_id: str) -> list[dict]:
        """Fetch all departments for a clinic."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT id, name FROM departments WHERE clinic_id = %s ORDER BY name", (clinic_id,))
                    return list(cur.fetchall())
        except Exception as e:
            print(f"[DB] Error getting departments: {e}")
            return []

    def get_doctors(self, clinic_id: str) -> list[dict]:
        """Fetch all active doctors along with their department names."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT d.id, d.name, d.calendar_id, dept.name as department
                        FROM doctors d
                        JOIN departments dept ON d.department_id = dept.id
                        WHERE d.active = TRUE AND d.clinic_id = %s
                        ORDER BY d.name
                    """, (clinic_id,))
                    return list(cur.fetchall())
        except Exception as e:
            print(f"[DB] Error getting doctors: {e}")
            return []

    def get_doctors_by_department(self, clinic_id: str, dept_name: str) -> list[dict]:
        """Fetch active doctors under a specific department (case-insensitive)."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT d.id, d.name, d.calendar_id, dept.name as department
                        FROM doctors d
                        JOIN departments dept ON d.department_id = dept.id
                        WHERE d.active = TRUE AND d.clinic_id = %s AND LOWER(dept.name) = LOWER(%s)
                        ORDER BY d.name
                    """, (clinic_id, dept_name.strip()))
                    return list(cur.fetchall())
        except Exception as e:
            print(f"[DB] Error getting doctors by department: {e}")
            return []

    def find_patient_by_phone(self, clinic_id: str, phone: str) -> dict | None:
        """
        Locates a patient record by hashing the phone number and doing an indexed lookup.
        Decrypts patient name/phone/DOB on successful match using client-side key.
        """
        # Clean phone input to match seed formatting (+919876543210)
        clean_phone = phone.strip().replace(" ", "").replace("-", "")

        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Calculate HMAC of phone in Python or SQL. We use SQL hmac() + encode()
                    cur.execute("""
                        SELECT id,
                               pgp_sym_decrypt(name_enc, %s) as name,
                               pgp_sym_decrypt(phone_enc, %s) as phone,
                               pgp_sym_decrypt(dob_enc, %s) as dob
                        FROM patients
                        WHERE phone_hash = encode(hmac(%s, %s, 'sha256'), 'hex')
                    """, (self.enc_key, self.enc_key, self.enc_key, clean_phone, self.hmac_key))
                    return cur.fetchone()
        except Exception as e:
            print(f"[DB] Error finding patient by phone: {e}")
            return None

    def create_patient(self, clinic_id: str, name: str, phone: str, dob: str) -> str | None:
        """
        Inserts a new patient record.
        PII columns are encrypted via pgp_sym_encrypt with our APP_ENCRYPT_KEY.
        Deterministic phone_hash is generated with APP_HMAC_KEY.
        Returns the new patient UUID string.
        """
        clean_phone = phone.strip().replace(" ", "").replace("-", "")

        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO patients (clinic_id, name_enc, phone_enc, dob_enc, phone_hash)
                        VALUES (
                            %s,
                            pgp_sym_encrypt(%s, %s),
                            pgp_sym_encrypt(%s, %s),
                            pgp_sym_encrypt(%s, %s),
                            encode(hmac(%s, %s, 'sha256'), 'hex')
                        )
                        RETURNING id
                    """, (clinic_id, name, self.enc_key, clean_phone, self.enc_key, dob, self.enc_key, clean_phone, self.hmac_key))
                    conn.commit()
                    return cur.fetchone()[0]
        except Exception as e:
            print(f"[DB] Error creating patient: {e}")
            return None

    def get_patient_booking(self, clinic_id: str, patient_id: str) -> dict | None:
        """Fetch the most recent active booking for a patient."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT b.id, b.patient_id, b.doctor_id, d.name as doctor_name,
                               dept.name as department, b.start_time, b.end_time, b.status
                        FROM bookings b
                        JOIN doctors d ON b.doctor_id = d.id
                        JOIN departments dept ON d.department_id = dept.id
                        WHERE b.patient_id = %s AND b.status IN ('pending', 'booked')
                        ORDER BY b.start_time DESC
                        LIMIT 1
                    """, (patient_id,))
                    return cur.fetchone()
        except Exception as e:
            print(f"[DB] Error getting patient booking: {e}")
            return None

    def create_booking(self, clinic_id: str, patient_id: str, doctor_id: str,
                       start_time, end_time, ext_event_id: str = None) -> str | None:
        """
        Creates a new booking record.
        Returns the booking UUID string.
        If double-booking range exclusion constraint is violated, raises a psycopg2 error.
        """
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO bookings (clinic_id, patient_id, doctor_id, start_time, end_time, status, ext_event_id)
                        VALUES (%s, %s, %s, %s, %s, 'booked', %s)
                        RETURNING id
                    """, (clinic_id, patient_id, doctor_id, start_time, end_time, ext_event_id))
                    conn.commit()
                    return cur.fetchone()[0]
        except Exception as e:
            print(f"[DB] Error creating booking: {e}")
            return None

    def update_booking(self, clinic_id: str, booking_id: str, start_time, end_time, status: str = 'booked') -> bool:
        """Update existing booking times or status."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE bookings
                        SET start_time = %s, end_time = %s, status = %s
                        WHERE id = %s
                    """, (start_time, end_time, status, booking_id))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"[DB] Error updating booking: {e}")
            return False

    def cancel_booking(self, clinic_id: str, booking_id: str) -> bool:
        """Cancels an active booking by setting status='cancelled'."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE bookings
                        SET status = 'cancelled'
                        WHERE id = %s
                    """, (booking_id,))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"[DB] Error cancelling booking: {e}")
            return False

    def write_call_log(self, clinic_id: str, call_sid: str, outcome: str,
                       escalated: bool = False, matched_rule: str = None) -> bool:
        """Inserts a new call log entry."""
        try:
            with self._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO call_logs (clinic_id, call_sid, escalated, matched_rule, outcome)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (call_sid) DO UPDATE
                        SET escalated = EXCLUDED.escalated,
                            matched_rule = EXCLUDED.matched_rule,
                            outcome = EXCLUDED.outcome
                    """, (clinic_id, call_sid, escalated, matched_rule, outcome))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"[DB] Error writing call log: {e}")
            return False


# Singleton instance
db = DBService()
