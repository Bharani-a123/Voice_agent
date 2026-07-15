"""
booking_node — Handles new appointment booking (multi-turn).
Queries clinic departments, active doctors, and slot availability directly from Supabase DB.
Writes the confirmed booking to Supabase and Google Calendar.
"""

from datetime import datetime, timezone, timedelta
from langchain_core.messages import AIMessage
from agent.state import CallState
from agent.db_service import db
from agent.calendar_adapter import GoogleCalendarAdapter

calendar = GoogleCalendarAdapter(db)


def booking_node(state: CallState) -> dict:
    """Multi-turn booking handler. Query Supabase + Google Calendar."""

    clinic_id = state.get("clinic_id")
    step      = state.get("booking_step")
    text      = state.get("current_input", "")
    dept      = state.get("selected_department")
    doc_id    = state.get("selected_doctor_id")
    doc_nm    = state.get("selected_doctor_name")
    slot      = state.get("selected_slot")

    # Fetch departments from database
    departments = db.get_departments(clinic_id)
    dept_names  = [d["name"] for d in departments]

    # ── Step 1: No department yet — ask which department ──────────────────────
    if not dept:
        # Try to extract department from current input
        for d_name in dept_names:
            if d_name.lower() in text.lower():
                dept = d_name
                break

        if not dept:
            depts_text = ", ".join(dept_names)
            response = (
                f"I'd be happy to book an appointment for you! "
                f"We have the following departments: {depts_text}. "
                f"Which department would you like?"
            )
            return {
                "booking_step": "ask_department",
                "response":     response,
                "messages":     [AIMessage(content=response)],
            }

    # Fetch doctors for selected department
    doctors = db.get_doctors_by_department(clinic_id, dept)

    # ── Step 2: Have department, no doctor yet — ask which doctor ─────────────
    if not doc_id:
        # Try to match doctor from current input
        for d in doctors:
            if d["name"].lower() in text.lower() or \
               d["name"].split()[-1].lower() in text.lower():
                doc_id = d["id"]
                doc_nm = d["name"]
                break

        if not doc_id:
            doctors_list = " or ".join(d["name"] for d in doctors)
            response = (
                f"For {dept}, we have {doctors_list}. "
                f"Which doctor would you prefer?"
            )
            return {
                "selected_department": dept,
                "booking_step":        "ask_doctor",
                "response":            response,
                "messages":            [AIMessage(content=response)],
            }

    # Find the doctor's calendar ID from database list
    doctor_obj  = next((d for d in doctors if d["id"] == doc_id), None)
    calendar_id = doctor_obj["calendar_id"] if doctor_obj else "primary"

    # ── Step 3: Have doctor, no slot yet — show available slots ───────────────
    # We query availability only if we don't have a slot start/end persisted in state
    iso_start = state.get("selected_slot_start")
    iso_end   = state.get("selected_slot_end")

    if not slot or not iso_start:
        start_search = datetime.now(timezone.utc)
        end_search   = start_search + timedelta(days=2)
        available    = calendar.get_availability(clinic_id, calendar_id, start_search, end_search)

        # Try to match slot from current input
        matched_slot_obj = None
        for s in available:
            label_lower = s["label"].lower()
            if label_lower in text.lower() or \
               any(part in text.lower() for part in label_lower.split() if len(part) > 2):
                matched_slot_obj = s
                slot = s["label"]
                break

        if not slot or not matched_slot_obj:
            slots_text = ", ".join(s["label"] for s in available)
            response = (
                f"I have the following available slots with {doc_nm}: {slots_text}. "
                f"Which time works best for you?"
            )
            return {
                "selected_department":  dept,
                "selected_doctor_id":   doc_id,
                "selected_doctor_name": doc_nm,
                "booking_step":         "ask_slot",
                "response":             response,
                "messages":             [AIMessage(content=response)],
            }

        # Persist slot datetimes
        iso_start = matched_slot_obj["start"]
        iso_end   = matched_slot_obj["end"]

    # ── Step 4: Have all info — confirm with caller ───────────────────────────
    if state.get("booking_step") == "ask_slot" or (dept and doc_id and slot):
        confirm_words = ["yes", "confirm", "book it", "that's fine", "ok", "sure", "go ahead"]
        if any(w in text.lower() for w in confirm_words) or state.get("booking_step") == "confirm":

            # For guest/walk-in patient, use or create a default guest record
            patient_id = state.get("patient_id")
            if not patient_id:
                pat = db.find_patient_by_phone(clinic_id, "+919876543210")
                patient_id = pat["id"] if pat else db.create_patient(
                    clinic_id, "Guest Patient", "+919999888800", "1990-01-01"
                )

            # 1. Create Google Calendar event
            ext_event_id = calendar.create_event(
                clinic_id=clinic_id,
                calendar_id=calendar_id,
                summary=f"Appointment: {state.get('patient_name', 'Guest')} with {doc_nm}",
                start_time=datetime.fromisoformat(iso_start),
                end_time=datetime.fromisoformat(iso_end),
                description=f"MediCare Connect Voice Booking. Dept: {dept}"
            )

            # 2. Write booking to Supabase Database
            booking_id = db.create_booking(
                clinic_id=clinic_id,
                patient_id=patient_id,
                doctor_id=doc_id,
                start_time=iso_start,
                end_time=iso_end,
                ext_event_id=ext_event_id
            )

            response = (
                f"Your appointment has been booked! "
                f"You're scheduled with {doc_nm} ({dept}) at {slot}. "
                f"Your booking reference is {booking_id[:8].upper() if booking_id else 'BK-CONFIRMED'}. "
                f"Is there anything else I can help you with?"
            )
            return {
                "selected_department":  dept,
                "selected_doctor_id":   doc_id,
                "selected_doctor_name": doc_nm,
                "selected_slot":        slot,
                "booking_id":           booking_id,
                "booking_step":         "done",
                "current_intent":       None,
                "outcome":              "booked",
                "response":             response,
                "messages":             [AIMessage(content=response)],
            }

        # Ask for confirmation
        response = (
            f"Just to confirm — you'd like to book an appointment with "
            f"{doc_nm} ({dept}) at {slot}. Shall I go ahead and book that?"
        )
        return {
            "selected_department":  dept,
            "selected_doctor_id":   doc_id,
            "selected_doctor_name": doc_nm,
            "selected_slot":        slot,
            "selected_slot_start":  iso_start,
            "selected_slot_end":    iso_end,
            "booking_step":         "confirm",
            "response":             response,
            "messages":             [AIMessage(content=response)],
        }

    # Fallback
    depts_text = ", ".join(dept_names)
    response = f"I'd be happy to book an appointment. Which department do you need — {depts_text}?"
    return {
        "booking_step": "ask_department",
        "response":     response,
        "messages":     [AIMessage(content=response)],
    }
