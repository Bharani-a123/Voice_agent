# MediCare Connect — Problem Statement (v1 MVP)

## One-line pitch
A multi-tenant, voice-based AI receptionist that answers a clinic's real phone line via Twilio — handling appointment booking, rescheduling, and FAQ answering — while hard-guardrailing any symptom-related speech to immediate escalation to a human. Built as a real product, launching live with one pilot clinic.

---

## 1. Problem

Multi-specialty clinics lose significant staff time and patient goodwill to phone-based appointment scheduling. Front-desk staff spend hours daily on repetitive calls — booking, rescheduling, answering the same FAQs — leading to hold times, missed calls during peak hours, and inconsistent handling of urgent symptom reports.

## 2. Who this is for

Small-to-mid multi-specialty clinics. Launching with **one pilot clinic** in production; architecture is multi-tenant from day one so additional clinics can self-serve onboard after the pilot validates the model.

Each clinic:
- Self-serves signup and configures its own departments, doctors, and hours (no fixed department list across tenants)
- Connects its own Google Calendar / Outlook for live slot availability
- Configures its own escalation destination (a real nurse/staff phone number)

## 3. Scope — In

| Area | Detail |
|---|---|
| **Booking** | Book / reschedule / cancel appointments across clinic-configured departments |
| **Identity verification** | Name + phone/DOB, required only before touching an *existing* booking (reschedule/cancel) — not required for new bookings or FAQ |
| **FAQ (RAG)** | Grounded answers on timings, insurance, doctor specialization, first-visit requirements — scoped per clinic's own knowledge base |
| **Escalation guardrail** | Checked on **every conversational turn**, not just at intent detection. Any red-flag/urgent symptom language immediately overrides the current flow (booking, FAQ, anything) and routes live to that clinic's configured human nurse/staff number |
| **Voice pipeline** | Real-time, low-latency, over an actual Twilio phone number — live in production, not a simulation |
| **Multi-tenant admin** | Self-serve clinic signup; dashboard to configure departments, doctors, hours, escalation number, calendar connection |
| **Calendar integration** | Google Calendar / Outlook per clinic for real availability — no internal calendar system to maintain |
| **Data handling** | Minimal PHI only: name, phone, DOB — encrypted at rest, strict access control. **No symptom or clinical detail is ever stored** — only an `escalated: true/false` flag per call. Full HIPAA/BAA-grade compliance is explicitly deferred to a later phase; this reduced-data-footprint approach is disclosed to and agreed with the pilot clinic upfront, not hidden. |

## 4. Scope — Out (explicit, not an oversight)

- **No clinical/diagnostic advice of any kind** — hard-coded refusal + escalation only, never an LLM-generated medical answer
- **No payment processing** (patient-side)
- **No billing/subscription engine for clinics** — pricing model is a business decision, tracked separately from this technical build
- **No multi-language support** — English only, v1
- **No EHR / practice management system integration** — calendar only, not full clinical records systems
- **No self-authored red-flag symptom list treated as clinically final** — sourced from public telephone-triage guidelines (e.g., NHS 111, Manchester Triage) as a starting point, explicitly flagged for licensed-clinician review before scaling past the pilot
- **No full HIPAA compliance / BAA-covered infrastructure** in v1 — deferred, with the reduced-PHI-footprint mitigation above as the interim safeguard

## 5. Constraints

- **Team:** Solo build
- **Timeline:** Several weeks
- **Budget:** Tight — cheapest viable API stack across STT / TTS / LLM / Twilio. Cost-per-call is a hard design constraint, not just a metric measured after the fact.
- **Scale target for v1:** One pilot clinic in live production; architecture supports more but onboarding more clinics is not a v1 goal

## 6. Architecture snapshot (reference — see separate design doc for full detail)

```
Caller → Twilio (PSTN + Media Streams)
       → Streaming STT
       → LangGraph orchestrator
           - Intent routing: Book | Reschedule/Cancel | FAQ | Escalate | Unclear
           - Escalation check runs on every turn, in parallel/preempting all other nodes
           - Identity verification gates only Reschedule/Cancel
           - RAG (per-clinic knowledge base) for FAQ
           - Retry-then-escalate on repeated "Unclear" (max 2 retries)
       → Streaming TTS
       → back to caller

Escalation → live transfer to clinic's configured human number
Booking data → per-clinic Google Calendar / Outlook
Identity + booking metadata → encrypted DB, no clinical data stored
```

## 7. Success criteria

| Metric | Target / Notes |
|---|---|
| End-to-end response latency | To be benchmarked against chosen STT/LLM/TTS stack; pin an exact number (e.g., <1.5s) before build sign-off |
| Booking task completion rate | % of calls completing booking/reschedule/cancel without human handoff |
| FAQ answer accuracy | Measured against a per-clinic test question set |
| Escalation recall | **~100%** on a red-flag-symptom test set — false negatives defeat the guardrail's entire purpose; precision can be lower, recall cannot |
| Cost per call | Tracked explicitly given the tight-budget constraint; not just reported, actively designed against |
| **Pilot validation metric** | Staff hours saved per week at the pilot clinic — the real business proof point, since "done" for this MVP means a real clinic using it in production, not just a working demo |

## 8. Known open risks (carried forward, not resolved by this document)

1. **Reduced-PHI approach still needs the pilot clinic's explicit sign-off** before go-live — this is a legal/business step, not a technical one.
2. **Red-flag symptom list needs clinician review** before any clinic beyond the pilot goes live.
3. **Exact latency target and cost-per-call ceiling** are pending a benchmarking pass on the selected STT/LLM/TTS vendors — flagged here so they don't get silently skipped.
4. **Barge-in / mid-speech interruption handling** (e.g., caller reports a symptom while TTS is still talking) needs explicit design — not yet specified beyond "the escalation check runs every turn."

---

*This document defines what MediCare Connect v1 is and is not. Next steps: mock data / schema design, then the LangGraph state machine implementation.*
