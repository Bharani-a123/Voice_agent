"""
Mock data for Phase 2 (text-only testing).
In Phase 3, these are replaced by real Supabase DB queries + Google Calendar API calls.
The mock data mirrors exactly what was seeded in Phase 1.
"""

from datetime import datetime, timedelta, timezone

# ── Pilot Clinic ──────────────────────────────────────────────────────────────
PILOT_CLINIC = {
    "id": "d72164a7-dd69-45c2-ac65-92c588b303a8",
    "name": "Greenfield Multi-Specialty Clinic",
    "timezone": "Asia/Kolkata",
    "escalation_phone": "+911800123456",
}

# ── Departments ───────────────────────────────────────────────────────────────
DEPARTMENTS = [
    {"id": "dept-cardio-001", "name": "Cardiology"},
    {"id": "dept-ortho-001",  "name": "Orthopaedics"},
]

# ── Doctors ───────────────────────────────────────────────────────────────────
DOCTORS = [
    {
        "id":            "doc-001",
        "name":          "Dr. Priya Sharma",
        "department":    "Cardiology",
        "department_id": "dept-cardio-001",
        "calendar_id":   "cal_priya_sharma@greenfield.clinic",
    },
    {
        "id":            "doc-002",
        "name":          "Dr. Arjun Mehta",
        "department":    "Cardiology",
        "department_id": "dept-cardio-001",
        "calendar_id":   "cal_arjun_mehta@greenfield.clinic",
    },
    {
        "id":            "doc-003",
        "name":          "Dr. Kavitha Rajan",
        "department":    "Orthopaedics",
        "department_id": "dept-ortho-001",
        "calendar_id":   "cal_kavitha_rajan@greenfield.clinic",
    },
]

# ── Patients (mock — real ones are encrypted in Supabase) ─────────────────────
MOCK_PATIENTS = [
    {
        "id":    "patient-001",
        "name":  "Ravi Kumar",
        "phone": "+919876543210",
        "dob":   "1985-03-15",
    },
    {
        "id":    "patient-002",
        "name":  "Sunita Patel",
        "phone": "+919123456789",
        "dob":   "1972-08-22",
    },
]

# ── Existing bookings (mock) ──────────────────────────────────────────────────
MOCK_BOOKINGS = [
    {
        "id":          "booking-001",
        "patient_id":  "patient-001",
        "patient_name":"Ravi Kumar",
        "doctor_id":   "doc-001",
        "doctor_name": "Dr. Priya Sharma",
        "department":  "Cardiology",
        "start_time":  "Tomorrow at 10:00 AM",
        "status":      "booked",
    },
]

# ── Clinic FAQ content (stub — real content goes to Qdrant in Phase 4) ────────
FAQ_CONTENT = {
    "hours":      "Greenfield Clinic is open Monday to Saturday, 8:00 AM to 8:00 PM. We are closed on Sundays.",
    "insurance":  "We accept most major insurance plans including Star Health, New India, HDFC Ergo, and ICICI Lombard. Please call ahead to confirm your specific plan.",
    "location":   "We are located at 12 MG Road, Bangalore. Ample parking is available in the basement.",
    "cardiology": "Our Cardiology department is led by Dr. Priya Sharma and Dr. Arjun Mehta, both with over 15 years of experience.",
    "ortho":      "Orthopaedics consultations are handled by Dr. Kavitha Rajan, specialist in joint replacement and sports injuries.",
    "first_visit":"For your first visit, please bring a valid government ID, your insurance card, and any previous medical records or test reports.",
    "emergency":  "For medical emergencies, please call 112 immediately or go to your nearest emergency room. We are not an emergency facility.",
}


# ── Helper functions ──────────────────────────────────────────────────────────

def get_departments_text() -> str:
    return ", ".join(d["name"] for d in DEPARTMENTS)


def get_doctors_text() -> str:
    return "; ".join(f"{d['name']} ({d['department']})" for d in DOCTORS)


def get_doctors_by_department(department_name: str) -> list:
    dept_lower = department_name.lower()
    return [d for d in DOCTORS if dept_lower in d["department"].lower()]


def get_available_slots(doctor_id: str, num_slots: int = 3) -> list:
    """
    Returns mock available slots for a doctor.
    In Phase 3, this calls the Google Calendar / Outlook API.
    """
    base = datetime.now(tz=timezone.utc) + timedelta(days=1)
    base = base.replace(hour=4, minute=30, second=0, microsecond=0)  # 10:00 AM IST

    slots = []
    for i in range(num_slots):
        slot_start = base + timedelta(hours=i)
        ist_hour = (slot_start.hour + 5) % 24
        ist_min  = (slot_start.minute + 30) % 60
        am_pm    = "AM" if ist_hour < 12 else "PM"
        display_hour = ist_hour if ist_hour <= 12 else ist_hour - 12
        slots.append({
            "id":    f"slot-{doctor_id}-{i}",
            "start": slot_start.isoformat(),
            "label": f"Tomorrow at {display_hour}:{ist_min:02d} {am_pm} IST",
        })
    return slots


def verify_patient_identity(name: str, phone: str) -> dict:
    """
    Checks if name+phone match a known patient.
    In Phase 3, this queries patients table using phone_hash lookup.
    Returns { verified: bool, patient_id: str|None, patient_name: str|None }
    """
    name_lower  = name.strip().lower()
    phone_clean = phone.strip().replace(" ", "").replace("-", "")

    for p in MOCK_PATIENTS:
        name_match  = name_lower in p["name"].lower() or p["name"].lower() in name_lower
        phone_match = phone_clean in p["phone"] or p["phone"] in phone_clean
        if name_match and phone_match:
            return {"verified": True, "patient_id": p["id"], "patient_name": p["name"]}

    return {"verified": False, "patient_id": None, "patient_name": None}


def get_patient_booking(patient_id: str) -> dict | None:
    """Returns the most recent active booking for a patient."""
    for b in MOCK_BOOKINGS:
        if b["patient_id"] == patient_id and b["status"] == "booked":
            return b
    return None


def create_mock_booking(patient_id: str, doctor_id: str, slot: str) -> str:
    """
    Creates a mock booking and returns a booking ID.
    In Phase 3, this writes to Postgres and Google Calendar.
    """
    import uuid
    booking_id = f"BK-{str(uuid.uuid4())[:8].upper()}"
    MOCK_BOOKINGS.append({
        "id":          booking_id,
        "patient_id":  patient_id,
        "patient_name":"Guest",
        "doctor_id":   doctor_id,
        "doctor_name": next((d["name"] for d in DOCTORS if d["id"] == doctor_id), "Doctor"),
        "department":  next((d["department"] for d in DOCTORS if d["id"] == doctor_id), ""),
        "start_time":  slot,
        "status":      "booked",
    })
    return booking_id
