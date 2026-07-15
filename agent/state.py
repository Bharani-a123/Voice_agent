"""
CallState — The state object that persists across all turns of one phone call.
Every node reads from and writes to this state.
"""

from typing import TypedDict, Optional, List, Annotated
from langchain_core.messages import BaseMessage
import operator


class CallState(TypedDict):
    # ── Conversation ──────────────────────────────────────────
    messages: Annotated[List[BaseMessage], operator.add]  # full turn history (accumulates)
    current_input: str       # what the caller just said (this turn)
    response: str            # AI response to send back to caller

    # ── Call context ──────────────────────────────────────────
    clinic_id: str
    call_sid: str

    # ── Intent tracking ───────────────────────────────────────
    # None = start of call, no intent yet
    current_intent: Optional[str]   # "book"|"reschedule"|"cancel"|"faq"|"unclear"|None
    intent_retries: int             # how many times we've been stuck in "unclear"

    # ── Booking state (multi-turn) ────────────────────────────
    selected_department: Optional[str]
    selected_doctor_id: Optional[str]
    selected_doctor_name: Optional[str]
    selected_slot: Optional[str]    # chosen time slot label
    selected_slot_start: Optional[str]  # ISO start time
    selected_slot_end: Optional[str]    # ISO end time
    booking_id: Optional[str]       # ID of confirmed booking
    booking_step: Optional[str]     # "ask_department"|"ask_doctor"|"ask_slot"|"confirm"|"done"

    # ── Identity verification ─────────────────────────────────
    identity_verified: bool
    patient_id: Optional[str]
    patient_name: Optional[str]
    identity_retries: int           # how many failed verification attempts

    # ── Escalation ────────────────────────────────────────────
    escalated: bool
    matched_rule: Optional[str]     # rule NAME that triggered (never stores symptom text)

    # ── Call outcome ──────────────────────────────────────────
    call_ended: bool
    outcome: Optional[str]          # "booked"|"rescheduled"|"cancelled"|"faq_answered"|"escalated"|"abandoned"


def initial_state(clinic_id: str, call_sid: str) -> CallState:
    """Create a fresh CallState for a new incoming call."""
    return CallState(
        messages=[],
        current_input="",
        response="",
        clinic_id=clinic_id,
        call_sid=call_sid,
        current_intent=None,
        intent_retries=0,
        selected_department=None,
        selected_doctor_id=None,
        selected_doctor_name=None,
        selected_slot=None,
        selected_slot_start=None,
        selected_slot_end=None,
        booking_id=None,
        booking_step=None,
        identity_verified=False,
        patient_id=None,
        patient_name=None,
        identity_retries=0,
        escalated=False,
        matched_rule=None,
        call_ended=False,
        outcome=None,
    )
