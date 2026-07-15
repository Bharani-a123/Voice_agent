"""
EscalationDetector — Two-layer safety guardrail.

Layer 1: Keyword/phrase rule match — cheap, deterministic, auditable.
         A clinician can read this list and reason about coverage.
         Sourced from NHS 111 / Manchester Triage red-flag categories.

Layer 2: LLM classifier for ambiguous cases that keywords miss.
         Deliberately NOT the same fast dialogue model used elsewhere.
         Uses Groq/Llama at temperature=0 for maximum determinism.

Design principle (non-negotiable):
  RECALL > PRECISION
  A false positive (routing to human when not needed) = acceptable.
  A false negative (missing a real emergency) = unacceptable.

This runs on EVERY conversational turn, not just at call start.
"""

import re
import os
from typing import Optional

# ── Red-flag keyword rules ────────────────────────────────────────────────────
# Each key = rule NAME (logged when triggered, NOT the patient's words)
# Each value = list of regex patterns
# Sourced from: NHS 111 red-flag categories + Manchester Triage System

ESCALATION_RULES: dict[str, list[str]] = {

    "chest_pain": [
        r"chest\s+pain", r"chest\s+tightness", r"chest\s+pressure",
        r"pain\s+in\s+(my\s+)?chest", r"heart\s+attack",
        r"heart\s+is\s+(racing|pounding|fluttering)",
        r"palpitation", r"my\s+heart\s+hurts",
    ],

    "breathing_difficulty": [
        r"can'?t\s+breath", r"cannot\s+breath", r"trouble\s+breath",
        r"difficulty\s+breath", r"shortness\s+of\s+breath",
        r"short\s+of\s+breath", r"struggling\s+to\s+breath",
        r"not\s+breath", r"wheezing", r"choking", r"gasping",
    ],

    "stroke_symptoms": [
        r"\bstroke\b", r"face\s+(is\s+)?drooping", r"arm\s+(is\s+)?weak",
        r"sudden\s+weakness", r"can'?t\s+speak", r"slurred\s+speech",
        r"sudden\s+confusion", r"sudden\s+numbness", r"sudden\s+vision",
        r"drooping\s+(face|on\s+one\s+side)", r"drooping",
    ],

    "unconscious_unresponsive": [
        r"unconscious", r"unresponsive", r"passed\s+out",
        r"fainted", r"not\s+waking", r"won'?t\s+wake",
        r"collapsed", r"fell\s+down\s+suddenly", r"blacked\s+out",
    ],

    "severe_bleeding": [
        r"severe\s+bleed", r"heavy\s+bleed", r"bleeding\s+badly",
        r"bleeding\s+heavily", r"bleeding\s+a\s+lot", r"won'?t\s+stop\s+bleed",
        r"blood\s+everywhere", r"hemorrhag", r"bleeding\s+profusely",
        r"bleed(ing)?\s+heavily",
    ],

    "allergic_reaction": [
        r"allergic\s+reaction", r"anaphylax", r"throat\s+(is\s+)?(closing|swelling)",
        r"tongue\s+swelling", r"can'?t\s+swallow", r"hives\s+all\s+over",
        r"severe\s+allergic",
    ],

    "overdose_poisoning": [
        r"\boverdose\b", r"took\s+too\s+many", r"poison(ing|ed)?",
        r"swallowed\s+something\s+(bad|wrong|harmful)",
        r"accidental\s+ingestion", r"drug\s+overdose",
    ],

    "severe_pain": [
        r"severe\s+pain", r"unbearable\s+pain", r"worst\s+pain",
        r"excruciating", r"10\s+(out\s+of\s+10|\/10)\s+pain",
        r"agony", r"can'?t\s+bear\s+the\s+pain",
    ],

    "mental_health_crisis": [
        r"want\s+to\s+(die|kill\s+myself)", r"kill\s+myself",
        r"\bsuicid(e|al)\b", r"\bself.?harm(ing|ed)?\b",
        r"have\s+been\s+self.?harm", r"hurt\s+myself", r"end\s+my\s+life",
    ],

    "seizure": [
        r"\bseizure\b", r"epilepsy\s+attack", r"\bconvulsion\b",
        r"\bconvuls(ing|ed|ion)\b", r"having\s+a\s+fit",
        r"fit\s+right\s+now", r"shaking\s+uncontrollably",
    ],

    "emergency_explicit": [
        r"\bemergency\b", r"\bambulance\b", r"call\s+1(12|08|00)",
        r"need\s+help\s+(right\s+now|immediately|urgently)",
        r"please\s+help\s+me\s+(now|please)",
    ],

    "infant_emergency": [
        r"baby\s+(fever|not\s+breathing|unresponsive|turning\s+blue)",
        r"infant\s+(fever|emergency)", r"newborn\s+(fever|emergency)",
        r"child\s+not\s+responding",
    ],

    "high_fever": [
        r"temperature\s+(of\s+)?(104|105|106|107|40|41|42)\s*(f|c|degrees)?",
        r"fever\s+(of\s+)?(104|105|106|107)", r"very\s+high\s+fever",
        r"burning\s+up\s+with\s+fever",
    ],
}


def _check_keywords(text: str) -> tuple[bool, Optional[str]]:
    """
    Fast regex-based keyword scan.
    Returns (escalate, rule_name_or_None).
    """
    text_lower = text.lower()
    for rule_name, patterns in ESCALATION_RULES.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return True, rule_name
    return False, None


def _check_llm(text: str) -> tuple[bool, Optional[str]]:
    """
    LLM-based classifier for ambiguous cases.
    Only runs when keyword check passes AND text has enough words.
    Fails SAFE: if LLM errors, returns escalate=True.
    """
    try:
        from langchain_groq import ChatGroq
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0,
            max_tokens=10,
            groq_api_key=os.environ["GROQ_API_KEY"],
        )

        system = (
            "You are a medical triage safety classifier. "
            "Respond ONLY with YES or NO.\n"
            "YES = patient describes any medical emergency, severe symptom, life-threatening condition, "
            "suicidal thought, or urgent physical distress.\n"
            "NO = routine appointment request, admin question, FAQ, or normal inquiry."
        )

        response = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=f'Patient said: "{text}"\nIs this a medical emergency? Answer YES or NO:'),
        ])

        answer = response.content.strip().upper()
        if answer.startswith("YES"):
            return True, "llm_classifier"
        return False, None

    except Exception:
        # LLM unavailable or errored — fail SAFE, escalate
        return True, "llm_error_failsafe"


class EscalationDetector:
    """
    Two-layer escalation detector. Call .check(text) on every user turn.

    Usage:
        detector = EscalationDetector()
        result = detector.check("I have chest pain")
        # result = { "escalate": True, "matched_rule": "chest_pain", "layer": "keyword" }
    """

    def check(self, text: str) -> dict:
        """
        Returns:
          escalate (bool): whether to immediately transfer to human
          matched_rule (str|None): rule name for logging (NEVER stores the patient's words)
          confidence (str): "high" | "medium"
          layer (str): "keyword" | "llm" | "none"
        """
        if not text or not text.strip():
            return {"escalate": False, "matched_rule": None, "confidence": "high", "layer": "none"}

        # Layer 1: Keywords (always runs, free, instant)
        escalate, rule = _check_keywords(text)
        if escalate:
            return {"escalate": True, "matched_rule": rule, "confidence": "high", "layer": "keyword"}

        # Layer 2: LLM for longer, potentially ambiguous utterances
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key and len(text.split()) >= 4:
            escalate, rule = _check_llm(text)
            if escalate:
                return {"escalate": True, "matched_rule": rule, "confidence": "medium", "layer": "llm"}

        return {"escalate": False, "matched_rule": None, "confidence": "high", "layer": "none"}


# Singleton — one instance shared across all nodes
detector = EscalationDetector()
