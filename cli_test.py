"""
cli_test.py — Interactive CLI to test the voice agent brain (Phase 2, text-only).
Simulates a phone call turn by turn. No Twilio, no STT, no TTS — pure text.

Usage:
    python cli_test.py

Type your messages as if you're the patient calling the clinic.
Type 'quit' or 'exit' to end the call.
Type 'state' to see the current call state.
Type 'reset' to start a fresh call.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Verify GROQ_API_KEY is set
if not os.environ.get("GROQ_API_KEY"):
    print("\n ERROR: GROQ_API_KEY not set in .env file")
    print(" Get a free key at https://console.groq.com")
    print(" Then add it to your .env: GROQ_API_KEY=gsk_...\n")
    sys.exit(1)

from agent.graph import graph
from agent.state import initial_state
from agent.mock_data import PILOT_CLINIC

CLINIC_NAME = PILOT_CLINIC["name"]
DIVIDER     = "-" * 60


def print_header():
    print(f"\n{'=' * 60}")
    print(f"  MediCare Connect — Voice Agent Brain Test (Phase 2)")
    print(f"  Clinic: {CLINIC_NAME}")
    print(f"{'=' * 60}")
    print("  Commands: 'state' = show call state | 'reset' = new call | 'quit' = exit")
    print(f"{DIVIDER}\n")


def print_state(state: dict):
    """Pretty-print current call state for debugging."""
    print(f"\n{'-' * 40} CALL STATE {'-' * 8}")
    print(f"  intent          : {state.get('current_intent', 'none')}")
    print(f"  intent_retries  : {state.get('intent_retries', 0)}")
    print(f"  identity_verified: {state.get('identity_verified', False)}")
    print(f"  patient_name    : {state.get('patient_name', '-')}")
    print(f"  booking_step    : {state.get('booking_step', '-')}")
    print(f"  department      : {state.get('selected_department', '-')}")
    print(f"  doctor          : {state.get('selected_doctor_name', '-')}")
    print(f"  slot            : {state.get('selected_slot', '-')}")
    print(f"  escalated       : {state.get('escalated', False)}")
    print(f"  matched_rule    : {state.get('matched_rule', '-')}")
    print(f"  outcome         : {state.get('outcome', '-')}")
    print(f"  turns           : {len(state.get('messages', []))}")
    print(f"{'-' * 60}\n")


def run_turn(state: dict, user_input: str) -> dict:
    """Run one turn through the LangGraph brain."""
    state["current_input"] = user_input
    updated = graph.invoke(state)
    return updated


def main():
    print_header()

    # Initial greeting (before first user input)
    greeting = (
        f"Thank you for calling {CLINIC_NAME}. "
        "I'm your AI receptionist. I can help you book, reschedule, "
        "or cancel an appointment, or answer questions about our clinic. "
        "How can I assist you today?"
    )
    print(f"  Receptionist: {greeting}\n")

    # Initialize call state
    state = initial_state(
        clinic_id=PILOT_CLINIC["id"],
        call_sid="CLI-TEST-001",
    )

    turn_num = 1

    while True:
        try:
            user_input = input(f"  You [{turn_num}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n  [Call ended by user]\n")
            break

        if not user_input:
            continue

        # Special commands
        if user_input.lower() in ("quit", "exit", "bye", "goodbye"):
            print(f"\n  Receptionist: Thank you for calling {CLINIC_NAME}. Have a great day!\n")
            break

        if user_input.lower() == "state":
            print_state(state)
            continue

        if user_input.lower() == "reset":
            state = initial_state(
                clinic_id=PILOT_CLINIC["id"],
                call_sid=f"CLI-TEST-{turn_num:03d}",
            )
            turn_num = 1
            print(f"\n  [New call started]\n  Receptionist: {greeting}\n")
            continue

        # Run through the graph
        print(f"\n  [Processing...]\n")
        try:
            state = run_turn(state, user_input)
        except Exception as e:
            print(f"\n  [ERROR in graph: {e}]")
            print("  Try typing 'reset' to start a fresh call.\n")
            continue

        response = state.get("response", "")
        print(f"  Receptionist: {response}\n")

        # Check if call ended (escalated or completed)
        if state.get("call_ended") or state.get("escalated"):
            print(f"  {DIVIDER}")
            print(f"  [CALL ENDED] Outcome: {state.get('outcome', 'unknown')}")
            if state.get("escalated"):
                print(f"  [ESCALATED] Rule: {state.get('matched_rule', '?')}")
                print(f"  [ACTION] In production: Twilio transfers to {PILOT_CLINIC['escalation_phone']}")
            print(f"  {DIVIDER}\n")

            restart = input("  Start a new call? (yes/no): ").strip().lower()
            if restart in ("yes", "y"):
                state = initial_state(
                    clinic_id=PILOT_CLINIC["id"],
                    call_sid=f"CLI-TEST-{turn_num:03d}",
                )
                turn_num = 0
                print(f"\n  [New call started]\n  Receptionist: {greeting}\n")
            else:
                break

        turn_num += 1


if __name__ == "__main__":
    main()
