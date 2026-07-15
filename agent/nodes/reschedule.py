"""
reschedule_node — Handles appointment rescheduling (post identity verification).
Queries active bookings from Supabase, fetches doctor availability from Google Calendar,
and updates both systems on confirmation.
"""

from datetime import datetime, timezone, timedelta
from langchain_core.messages import AIMessage
from agent.state import CallState
from agent.db_service import db
from agent.calendar_adapter import GoogleCalendarAdapter

calendar = GoogleCalendarAdapter(db)


def reschedule_node(state: CallState) -> dict:
    """Handles rescheduling after identity has been verified."""
    clinic_id  = state.get("clinic_id")
    patient_id = state.get("patient_id")
    text       = state.get("current_input", "")
    slot       = state.get("selected_slot")

    # 1. Find existing active booking
    booking = db.get_patient_booking(clinic_id, patient_id)
    if not booking:
        response = (
            "I don't see any active appointments under your name. "
            "Would you like to book a new appointment instead?"
        )
        return {
            "current_intent": None,
            "response":       response,
            "messages":       [AIMessage(content=response)],
        }

    # Fetch doctor calendar ID
    doctors = db.get_doctors(clinic_id)
    doctor_obj = next((d for d in doctors if d["name"] == booking["doctor_name"]), None)
    calendar_id = doctor_obj["calendar_id"] if doctor_obj else "primary"
    doctor_id   = doctor_obj["id"] if doctor_obj else booking["doctor_id"]

    # Query availability for the doctor
    start_search = datetime.now(timezone.utc)
    end_search   = start_search + timedelta(days=2)
    available    = calendar.get_availability(clinic_id, calendar_id, start_search, end_search)

    # 2. Offer slots if none selected yet
    if not slot:
        # Try to match slot from user input
        for s in available:
            label_lower = s["label"].lower()
            if label_lower in text.lower() or \
               any(part in text.lower() for part in label_lower.split() if len(part) > 2):
                slot = s["label"]
                break

        if not slot:
            slots_text = ", ".join(s["label"] for s in available)
            response = (
                f"Your current appointment is with {booking['doctor_name']} "
                f"at {booking['start_time'].strftime('%I:%M %p') if isinstance(booking['start_time'], datetime) else booking['start_time']}. "
                f"I have these available slots for rescheduling: {slots_text}. "
                f"Which time works for you?"
            )
            return {
                "response": response,
                "messages": [AIMessage(content=response)],
            }

    # Match slot label back to ISO dates
    selected_slot_obj = next((s for s in available if s["label"] == slot), None)
    iso_start = selected_slot_obj["start"] if selected_slot_obj else None
    iso_end   = selected_slot_obj["end"] if selected_slot_obj else None

    # 3. Confirm reschedule
    confirm_words = ["yes", "confirm", "reschedule it", "that's fine", "ok", "sure"]
    if any(w in text.lower() for w in confirm_words):

        # Extract old external event ID if exists to clean up
        with db._get_conn(clinic_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ext_event_id FROM bookings WHERE id = %s", (booking["id"],))
                row = cur.fetchone()
                old_event_id = row[0] if row else None

        # 1. Delete old event
        if old_event_id:
            calendar.delete_event(clinic_id, calendar_id, old_event_id)

        # 2. Create new event
        new_event_id = calendar.create_event(
            clinic_id=clinic_id,
            calendar_id=calendar_id,
            summary=f"Rescheduled Appointment: {state.get('patient_name', 'Patient')} with {booking['doctor_name']}",
            start_time=datetime.fromisoformat(iso_start),
            end_time=datetime.fromisoformat(iso_end),
            description=f"MediCare Connect Rescheduling. Dept: {booking['department']}"
        )

        # 3. Update database record
        success = db.update_booking(
            clinic_id=clinic_id,
            booking_id=booking["id"],
            start_time=iso_start,
            end_time=iso_end,
            status='booked'
        )

        # Update event ID in DB
        if success and new_event_id:
            with db._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE bookings SET ext_event_id = %s WHERE id = %s", (new_event_id, booking["id"]))
                    conn.commit()

        response = (
            f"Done! Your appointment with {booking['doctor_name']} has been "
            f"rescheduled to {slot}. Is there anything else I can help with?"
        )
        return {
            "selected_slot":  slot,
            "current_intent": None,
            "outcome":        "rescheduled",
            "response":       response,
            "messages":       [AIMessage(content=response)],
        }

    response = (
        f"Just to confirm — you'd like to reschedule your appointment with "
        f"{booking['doctor_name']} to {slot}. Shall I go ahead?"
    )
    return {
        "selected_slot": slot,
        "response":      response,
        "messages":      [AIMessage(content=response)],
    }
