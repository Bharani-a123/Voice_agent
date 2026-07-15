"""
test_escalation.py — Automated red-flag test suite for the EscalationDetector.

Tests 30 utterances across all 13 rule categories.
All must return escalate=True.
Then tests 10 normal utterances that must NOT escalate.

Run: python -m pytest tests/test_escalation.py -v
"""

import pytest
from agent.escalation import EscalationDetector

detector = EscalationDetector()


# ── RED FLAG utterances — ALL must escalate ───────────────────────────────────

RED_FLAG_CASES = [
    # chest_pain
    ("chest_pain_direct",      "I have chest pain"),
    ("chest_pain_pressure",    "There is a lot of chest pressure and tightness"),
    ("heart_attack",           "I think I am having a heart attack"),
    ("heart_palpitation",      "My heart is racing and I have palpitations"),

    # breathing_difficulty
    ("cant_breathe",           "I can't breathe properly"),
    ("shortness_of_breath",    "I am having shortness of breath"),
    ("breathing_trouble",      "I am struggling to breathe and wheezing"),

    # stroke_symptoms
    ("stroke_word",            "I think I am having a stroke"),
    ("face_drooping",          "His face is drooping on one side"),
    ("slurred_speech",         "My mother has slurred speech suddenly"),

    # unconscious
    ("unconscious",            "My father is unconscious and not waking up"),
    ("passed_out",             "She passed out on the floor"),
    ("collapsed",              "He collapsed and won't respond"),

    # severe_bleeding
    ("severe_bleeding",        "There is severe bleeding that won't stop"),
    ("heavy_bleed",            "She is bleeding heavily from her arm"),

    # allergic_reaction
    ("anaphylaxis",            "I think I am having anaphylaxis"),
    ("throat_closing",         "My throat is closing and I can't swallow"),

    # overdose
    ("overdose",               "My son took an overdose of pills"),
    ("swallowed_wrong",        "He swallowed something bad by accident"),

    # severe_pain
    ("severe_pain",            "I have severe unbearable pain everywhere"),
    ("excruciating",           "The pain is excruciating I cannot bear it"),

    # mental_health_crisis
    ("suicidal",               "I am feeling suicidal and want to end my life"),
    ("self_harm",              "I have been self-harming"),

    # seizure
    ("seizure",                "She is having a seizure right now"),
    ("convulsion",             "He is convulsing on the floor"),

    # emergency_explicit
    ("emergency_word",         "This is a medical emergency please help"),
    ("need_ambulance",         "I need an ambulance right now"),

    # infant_emergency
    ("baby_not_breathing",     "My baby is not breathing please help"),

    # high_fever
    ("very_high_fever",        "His temperature is 104 F and very high fever"),

    # indirect but concerning
    ("cant_speak",             "I can't speak suddenly and my arm is weak"),
]


# ── SAFE utterances — NONE must escalate ─────────────────────────────────────

SAFE_CASES = [
    ("book_appointment",       "I want to book an appointment with a cardiologist"),
    ("reschedule_appt",        "I need to reschedule my appointment please"),
    ("cancel_appt",            "Can I cancel my appointment tomorrow"),
    ("clinic_hours",           "What are your clinic timings"),
    ("insurance_question",     "Do you accept Star Health insurance"),
    ("location_question",      "Where is the clinic located"),
    ("doctor_available",       "Is Dr. Priya Sharma available next week"),
    ("first_visit_question",   "What should I bring for my first visit"),
    ("mild_fever",             "I have a mild fever since yesterday"),  # mild = safe
    ("general_unwell",         "I have been feeling a bit unwell"),
]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRedFlags:
    """All red-flag utterances must trigger escalation."""

    @pytest.mark.parametrize("name,utterance", RED_FLAG_CASES, ids=[c[0] for c in RED_FLAG_CASES])
    def test_escalates(self, name: str, utterance: str):
        result = detector.check(utterance)
        assert result["escalate"] is True, (
            f"MISSED RED FLAG [{name}]: '{utterance}'\n"
            f"  Result: {result}"
        )

    def test_all_red_flags_have_matched_rule(self):
        """Every escalated result must have a rule name (for audit logging)."""
        for name, utterance in RED_FLAG_CASES:
            result = detector.check(utterance)
            if result["escalate"]:
                assert result["matched_rule"] is not None, (
                    f"[{name}] escalated but matched_rule is None — cannot audit log"
                )


class TestSafeCases:
    """Safe utterances must NOT trigger escalation."""

    @pytest.mark.parametrize("name,utterance", SAFE_CASES, ids=[c[0] for c in SAFE_CASES])
    def test_does_not_escalate(self, name: str, utterance: str):
        result = detector.check(utterance)
        assert result["escalate"] is False, (
            f"FALSE POSITIVE [{name}]: '{utterance}'\n"
            f"  Result: {result}"
        )


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_string(self):
        result = detector.check("")
        assert result["escalate"] is False

    def test_whitespace_only(self):
        result = detector.check("   ")
        assert result["escalate"] is False

    def test_single_word_safe(self):
        result = detector.check("hello")
        assert result["escalate"] is False

    def test_case_insensitive(self):
        """Keywords must match regardless of case."""
        result = detector.check("CHEST PAIN")
        assert result["escalate"] is True

    def test_mixed_case(self):
        result = detector.check("Chest Pain Is Very Severe")
        assert result["escalate"] is True

    def test_result_has_all_keys(self):
        """Result dict must always have all expected keys."""
        result = detector.check("I want to book an appointment")
        assert "escalate" in result
        assert "matched_rule" in result
        assert "confidence" in result
        assert "layer" in result
