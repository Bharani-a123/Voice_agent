"""
cancel_node — Handles appointment cancellation (post identity verification).
Queries active bookings from Supabase, deletes event from Google Calendar,
and marks status as cancelled in Supabase.
"""

from langchain_core.messages import AIMessage
from agent.state import CallState
from agent.db_service import db
from agent.calendar_adapter import GoogleCalendarAdapter

calendar = GoogleCalendarAdapter(db)


def cancel_node(state: CallState) -> dict:
    """Handles cancellation after identity has been verified."""
    clinic_id  = state.get("clinic_id")
    patient_id = state.get("patient_id")
    text       = state.get("current_input", "")

    # Find existing booking
    booking = db.get_patient_booking(clinic_id, patient_id)
    if not booking:
        response = (
            "I don't see any active appointments under your name. "
            "Is there anything else I can help you with?"
        )
        return {
            "current_intent": None,
            "response":       response,
            "messages":       [AIMessage(content=response)],
        }

    # Ask for confirmation
    confirm_words = ["yes", "cancel it", "please cancel", "go ahead", "confirm", "ok", "sure"]
    if any(w in text.lower() for w in confirm_words):

        # Extract doctor calendar ID
        doctors = db.get_doctors(clinic_id)
        doctor_obj = next((d for d in doctors if d["name"] == booking["doctor_name"]), None)
        calendar_id = doctor_obj["calendar_id"] if doctor_obj else "primary"

        # Get external event ID from database
        with db._get_conn(clinic_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ext_event_id FROM bookings WHERE id = %s", (booking["id"],))
                row = cur.fetchone()
                event_id = row[0] if row else None

        # 1. Delete from Google Calendar
        if event_id:
            calendar.delete_event(clinic_id, calendar_id, event_id)

        # 2. Mark cancelled in database
        db.cancel_booking(clinic_id, booking["id"])

        response = (
            f"Your appointment with {booking['doctor_name']} at {booking['start_time']} "
            f"has been cancelled. Is there anything else I can help you with?"
        )
        return {
            "current_intent": None,
            "outcome":        "cancelled",
            "response":       response,
            "messages":       [AIMessage(content=response)],
        }

    response = (
        f"I found your appointment with {booking['doctor_name']} "
        f"at {booking['start_time']}. "
        f"Are you sure you'd like to cancel this appointment?"
    )
    return {
        "response": response,
        "messages": [AIMessage(content=response)],
    }
