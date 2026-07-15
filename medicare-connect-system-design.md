# MediCare Connect — System Design Document (v1, Production)

*Companion to `medicare-connect-problem-statement.md` and `medicare-connect-tech-stack.md`. This document is the full HLD + LLD: what to build, in what shape, so a solo developer can build directly from it.*

Context locked in from the source docs: solo dev, several weeks, one pilot clinic live in production, multi-tenant architecture from day one, real Twilio number, tight per-call budget, Google/Outlook calendar integration, ~100% recall required on the escalation guardrail, reduced-PHI footprint (no symptom/clinical data ever stored), full HIPAA/BAA deferred with pilot clinic sign-off.

---

## 1. Overview & requirements

### 1.1 Functional requirements
- Answer inbound calls on a real Twilio number, per clinic
- Book / reschedule / cancel appointments against clinic-configured departments and doctors
- Verify identity (name + phone/DOB) only before touching an existing booking
- Answer FAQs grounded in a per-clinic knowledge base (RAG)
- Detect red-flag/urgent symptom language on **every turn** and immediately live-transfer to the clinic's configured human number, preempting any in-progress flow
- Self-serve clinic onboarding: departments, doctors, hours, escalation number, calendar OAuth, FAQ documents
- Read/write real availability against the clinic's Google Calendar or Outlook

### 1.2 Non-functional requirements
- **Latency:** end-to-end response (caller stops speaking → TTS audio starts) target **<1.5s p50, <2.5s p95**. This is the single biggest UX risk in the system — pin it now rather than after benchmarking, per the open risk in the problem statement.
- **Escalation recall:** ~100% on the red-flag test set. This is a safety requirement, not a quality metric — it gets a dedicated design section (§5.4) and its own test gate before any go-live.
- **Availability:** target 99.5% for v1 (one pilot clinic, business-hours-weighted). Not 99.99% — that tier isn't justified by a single-tenant pilot and would cost real engineering time better spent on the guardrail.
- **Consistency:** booking writes must be consistent with the clinic's calendar (no double-booking). Everything else (FAQ freshness, dashboard reads) can be eventually consistent.
- **Durability:** call logs and booking records must survive infra failure — standard managed-Postgres backups are sufficient at this scale.
- **Compliance posture:** reduced-PHI footprint (name, phone, DOB only; no symptom/clinical text ever persisted) as an explicit interim safeguard, disclosed to and signed off by the pilot clinic. Full HIPAA/BAA-grade infrastructure is out of scope for v1 by design.

### 1.3 Scale estimate (stated assumption)
No real numbers exist yet — one pilot clinic, pre-launch. Assuming a mid-size multi-specialty clinic:
- ~50–150 inbound calls/day, concentrated in business hours (call it a peak of 10–15 concurrent calls in a busy hour, generously)
- Average call length: 2–4 minutes
- This is **not a high-QPS system.** Peak concurrent calls will be in the low tens, not thousands. This estimate changes several downstream decisions (§2, §5) — a lot of "how do we scale this" thinking in a generic system design doc is over-engineering here and is explicitly called out as such rather than applied by default.

### 1.4 Explicit non-goals (carried from problem statement, restated for the build)
No clinical/diagnostic LLM output; no patient-side payments; no billing engine; English only; no EHR integration; no self-authored red-flag list treated as clinically final (sourced from public triage guidelines, flagged for clinician review pre-scale); no full HIPAA/BAA infra in v1.

---

## 2. Architecture style

- **Modular monolith over microservices.** Solo dev, several-week timeline, low concurrency — microservices would add deployment and network-boundary overhead with zero payoff at this scale. Two deployable units total: (1) the voice gateway + LangGraph orchestrator as one long-running service, (2) the admin dashboard (Next.js) as a separate app, because they have genuinely different runtime needs (persistent WebSocket vs request/response).
- **Hybrid request-driven / stateful-per-call.** Each call is a stateful session (conversation state, turn history, identity-verification status) held in the orchestrator process for the call's duration — not a stream of independent stateless requests. State does not need to survive process restart mid-call for v1 (a dropped call mid-restart is an acceptable, rare failure mode at this scale — reconnecting a live phone call mid-flight is not realistically recoverable regardless of architecture).
- **Long-running services, not serverless**, for the voice gateway and orchestrator — Twilio Media Streams requires a persistent WebSocket, which serverless platforms (Vercel functions, Lambda) handle badly, as already correctly identified in the tech-stack doc. The admin dashboard is the opposite case: bursty, stateless HTTP, a good fit for Vercel serverless.
- **Stateful component:** the orchestrator process (in-memory call state). **Stateless components:** admin dashboard, calendar sync jobs. **Persistent state:** Postgres (source of truth for everything durable) and Qdrant (FAQ embeddings).

---

## 3. High-level architecture

See the diagram above for the call-time data flow. In prose: a call arrives on the clinic's Twilio number, Twilio opens a Media Streams WebSocket to the voice gateway, which forwards audio to Deepgram for streaming STT and forwards synthesized audio back from ElevenLabs. Transcript chunks feed the LangGraph orchestrator, which runs the escalation check on every turn (in parallel with, and capable of preempting, whatever node is active), routes intent, verifies identity when touching an existing booking, answers FAQs via RAG against that clinic's Qdrant collection, and reads/writes the clinic's calendar for bookings. Every outcome is logged to Postgres with no symptom content stored — only an `escalated: true/false` flag.

The admin dashboard is a separate Next.js app used only by clinic staff for one-time and occasional config (departments, doctors, hours, escalation number, calendar OAuth, FAQ upload) — it is never in the hot path of a live call.

### 3.1 Component responsibilities

| Component | Responsibility | Why this boundary |
|---|---|---|
| Voice gateway | Twilio Media Streams termination, audio framing, STT/TTS bridging, barge-in detection | Isolates the one genuinely latency-critical, protocol-heavy piece so it can be reasoned about and load-tested independently |
| LangGraph orchestrator | Turn-level state machine: escalation check, intent routing, identity gate, RAG, booking logic | This is the product's core logic and its most reusable artifact — kept as pure application logic, decoupled from the transport (voice gateway) below it |
| Calendar adapter | Thin abstraction over Google Calendar API / Microsoft Graph, per clinic OAuth tokens | Isolates two different third-party APIs behind one interface so the orchestrator doesn't branch on `calendar_provider` everywhere |
| Admin dashboard + API | Tenant self-serve config | Decoupled from the call path entirely — a dashboard outage must never take down live calls |

---

## 4. Data layer

### 4.1 Storage choice
- **Postgres** for all structured, transactional data (tenants, bookings, identity, call logs). Justification: bookings need transactional writes with real constraints (no double-booking a doctor's slot), and the admin dashboard needs join-heavy queries (clinic → departments → doctors → bookings) that a document store would fight. This was already the right call in the tech-stack doc; restating the reasoning here.
- **Qdrant** for FAQ embeddings, filtered by `clinic_id` metadata rather than one collection per tenant — keeps ops overhead at zero for a single pilot clinic while the filter model already supports more tenants without re-architecture.
- **No Redis/cache layer for v1.** At low tens of concurrent calls, Postgres read latency for tenant config (departments, hours, escalation number) is not a bottleneck — a cache here would be premature optimization solving a problem that doesn't exist yet. Revisit only if per-call config lookups show up in latency profiling (§5).

### 4.2 Schema (extends the tech-stack doc's table list with actual columns and constraints)

```
clinics
  id                    uuid PK
  name                  text
  timezone              text
  escalation_phone_e164 text                 -- validated E.164 format
  calendar_provider     enum('google','outlook')
  calendar_oauth_ref    text                 -- pointer to encrypted token row, not the token itself
  status                enum('onboarding','active','suspended')
  created_at            timestamptz

departments
  id          uuid PK
  clinic_id   uuid FK -> clinics
  name        text
  created_at  timestamptz

doctors
  id             uuid PK
  clinic_id      uuid FK -> clinics
  department_id  uuid FK -> departments
  name           text
  calendar_id    text        -- external calendar resource id
  active         boolean

patients
  id          uuid PK
  clinic_id   uuid FK -> clinics
  name_enc    bytea       -- pgcrypto encrypted
  phone_enc   bytea       -- pgcrypto encrypted
  dob_enc     bytea       -- pgcrypto encrypted
  phone_hash  text        -- deterministic hash for lookup, NOT reversible, indexed
  created_at  timestamptz
  -- no symptom/clinical column exists, by design

bookings
  id           uuid PK
  clinic_id    uuid FK -> clinics
  patient_id   uuid FK -> patients
  doctor_id    uuid FK -> doctors
  start_time   timestamptz
  end_time     timestamptz
  status       enum('pending','booked','rescheduled','cancelled','failed')
  ext_event_id text        -- calendar provider's event id, for idempotent writes
  created_at   timestamptz
  -- structural double-booking guard: range exclusion, not a plain unique constraint.
  -- a UNIQUE(doctor_id, start_time) only blocks identical start times — two bookings
  -- with overlapping but non-identical start times (10:00-10:30 vs 10:15-10:45)
  -- would sail right through it. Requires the btree_gist extension:
  --   EXCLUDE USING gist (doctor_id WITH =, tsrange(start_time, end_time) WITH &&)
  --   WHERE (status IN ('booked','pending'))

call_logs
  id            uuid PK
  clinic_id     uuid FK -> clinics
  call_sid      text        -- Twilio call sid
  escalated     boolean
  outcome       enum('booked','rescheduled','cancelled','faq_answered','escalated','abandoned','unclear_timeout')
  latency_ms_p50 int
  turn_count    int
  started_at    timestamptz
  ended_at      timestamptz
  -- no transcript, no symptom text — structurally absent, not just unpopulated

faq_documents
  id           uuid PK
  clinic_id    uuid FK -> clinics
  source_name  text
  qdrant_ids   text[]      -- chunk ids in the per-clinic-filtered Qdrant collection
  uploaded_at  timestamptz
```

**Design note on `patients`:** lookup during identity verification needs to match on phone/DOB without decrypting every row. `phone_hash` (a deterministic HMAC, not the encryption key used for `phone_enc`) gives an indexable lookup path while the actual PII stays encrypted at rest. This is the one place a naive implementation ("just query WHERE phone = ?") would either break encryption-at-rest or be O(n) on decrypt — worth calling out explicitly since it's a common LLD miss.

**Design note on `bookings`:** the double-booking guard is a range-exclusion constraint over `[start_time, end_time)` per doctor, not application-level "check then insert" logic, which races under concurrent calls — and not a plain `UNIQUE(doctor_id, start_time)` either, since that only blocks identical start times and misses overlapping-but-different ones. Database constraint > app-level check for this invariant.

**Design note on write ordering (Postgres ↔ calendar):** the booking write is not a single atomic operation — it spans two systems (Postgres and the clinic's calendar API) that don't share a transaction. The write path is: (1) insert into `bookings` with `status='pending'`, which is where the exclusion constraint actually catches conflicts, cheaply and locally; (2) only on successful insert, call the calendar API to create the event; (3) on calendar success, flip `status` to `booked`; on calendar failure, flip to `failed` and tell the caller there was an issue rather than confirming a booking that isn't on the real calendar. Postgres is deliberately the source of truth for "is this slot taken," not the calendar — that keeps the one invariant that matters (no double-booking) enforceable by a database constraint instead of a race between two APIs.

### 4.3 Replication / partitioning
Not needed for v1. A single managed Postgres instance (Supabase/Neon) with standard point-in-time recovery covers one pilot clinic. `tenant_id` (`clinic_id`) as a column rather than per-tenant databases, per the tech-stack doc — correct call, restated: it's the standard approach until physical isolation is required for compliance reasons at meaningfully larger scale, which is explicitly out of scope here.

### 4.4 Backup / DR
- Managed Postgres automated daily backups + point-in-time recovery (both Supabase and Neon provide this on free/starter tiers) — RPO of a few minutes, RTO of under an hour, which is more than adequate for a single-pilot-clinic system where the actual disaster scenario (a dropped call) is not equivalent to a data-loss event.
- Qdrant: FAQ embeddings are regenerable from `faq_documents.source_name` — treat Qdrant as a rebuildable cache, not a source of truth requiring its own backup discipline. This is a deliberate simplification that removes an entire DR concern for free.

---

## 5. Reliability, correctness & the escalation guardrail

This section is where "production-ready" is actually earned for this system — the rest is fairly standard CRUD-plus-voice plumbing.

### 5.1 Availability approach
Single-region deployment (Fly.io/Railway) is sufficient at pilot scale — multi-region active-active would be solving a problem this system doesn't have yet (one clinic, one timezone). Health checks on the voice gateway process; auto-restart on crash. The honest failure mode to design for is a mid-call process crash, not a regional outage.

### 5.2 What happens when a call is mid-flight and something fails
| Failure | Behavior |
|---|---|
| STT provider (Deepgram) errors/drops | Retry the stream once; on second failure, fail safe to **immediate escalation** — a caller who can't be understood by the system is a caller who should reach a human, not one who should be looped in a "sorry, I didn't catch that" retry indefinitely |
| LLM (Groq/Llama) errors/times out | One retry with backoff; on repeated failure, escalate rather than leave the caller in dead air |
| TTS (ElevenLabs) errors | Fall back to a pre-recorded "please hold" audio clip while retrying, then escalate if TTS stays down — never leave silence, since silence on a phone call reads as a dropped call to the caller |
| Calendar API errors (booking write) | Do not tell the caller "booked" until the calendar write is confirmed. On failure, tell the caller there was an issue and offer escalation or a callback, rather than silently failing while confirming success |
| Twilio transfer (escalation) fails | This is the one failure mode with no further fallback — log loudly, alert immediately (§9). There's no safe further degradation once escalation itself fails |

**Idempotency:** booking writes use the calendar provider's event id (`ext_event_id`) as an idempotency key — if the orchestrator retries a booking write after a timeout (uncertain whether the first attempt succeeded), it checks for an existing event before creating a duplicate. This matters specifically because retries-on-uncertain-failure are exactly the scenario in §5.2 above.

### 5.3 Retry-then-escalate on unclear intent
Per the problem statement: max 2 retries on "Unclear" intent before escalating. Worth stating explicitly as a reliability property, not just a UX nicety — it bounds the worst case for a confused caller to a small, predictable number of turns rather than an open-ended loop, and it means "the system gave up gracefully" is itself a tested, designed state rather than an edge case discovered in production.

### 5.4 The escalation guardrail — design in depth
This is the system's actual hard requirement (~100% recall) and deserves more than the one line in the tech-stack doc.

**Two-layer detection**, as the tech-stack doc specifies, with the reasoning made explicit:
1. **Rule-based keyword/phrase match, first.** Cheap, deterministic, auditable — a clinician or auditor can read the actual rule list and reason about coverage, which an LLM's internal decision boundary doesn't offer. Sourced from public telephone-triage guidelines (NHS 111 / Manchester Triage red-flag categories) as stated in the problem statement — explicitly not self-authored, explicitly flagged for licensed-clinician review before any clinic beyond the pilot goes live.
2. **Second-pass classifier model on anything ambiguous** — not the same fast dialogue-tier Llama model used for intent routing, deliberately. The rationale in the tech-stack doc is correct and worth keeping as a hard rule: recall matters more than latency or cost *at this one decision point only*. Every other part of the system optimizes for cost/latency; this one part is exempted, on purpose, in writing, so a future cost-cutting pass doesn't accidentally weaken it.

**Runs on every turn, not just at intent classification** — meaning it's structurally a parallel/preempting node in the LangGraph state machine, not a branch inside the booking or FAQ node. A caller who says "actually my chest has been hurting" three turns into a reschedule flow must trigger escalation immediately, not just at the start of the call. This needs its own graph edge type (a preempting check that can interrupt any other node), not a conditional buried in the booking node's logic — getting this graph shape right is the highest-leverage LLD decision in the whole system (§8).

**Testing gate, not a one-time check:** the red-flag test set (built from the same public triage guidelines) is a regression suite, run on every change to the prompt, the keyword list, or the classifier — recall is checked before every deploy that touches this path, not just once before pilot launch. Precision can regress; recall cannot, per the problem statement's own success criteria. This should be a CI gate (§12), not a manual pre-launch checklist item that quietly stops being checked after week one.

**Open risk, carried forward honestly:** barge-in (caller reports a symptom while TTS is still speaking) is flagged as unresolved in the problem statement. Design position for v1: the voice gateway's barge-in detection (interrupting TTS playback on new speech) must feed directly into the escalation check — i.e., barge-in isn't just a UX nicety for natural conversation, it's a safety-path requirement, because a caller interrupting to report a symptom is exactly the case where the system must not finish its sentence and then move on. This should be explicitly tested, not assumed to fall out of general barge-in support.

---

### 5.5 Traffic management — abuse protection on the phone line
Every vendor in the pipeline (Twilio, Deepgram, Groq, ElevenLabs) bills per-use. An inbound phone number with no per-caller or per-clinic volume cap is a denial-of-wallet vector — a handful of repeat or spam calls can run up real cost with zero code path involved, which cuts directly against the tight-budget constraint that shaped every other choice in this doc. This wasn't addressed elsewhere and needs to be: cap concurrent calls per clinic, track call volume by caller ANI (the number Twilio reports), and alert — not necessarily block outright, since a legitimate anxious re-caller shouldn't be locked out — on volume that's anomalous relative to the clinic's baseline call pattern. This is a cheap check to add and an expensive gap to leave open.

## 6. API / interface design

Two interfaces: the internal orchestrator-to-service contracts (not public APIs — this isn't a system with third-party API consumers in v1), and the admin dashboard's API.

### 6.1 Admin dashboard API (Next.js API routes, REST)
```
POST   /api/clinics                      create clinic (self-serve signup)
GET    /api/clinics/:id                  clinic config
PATCH  /api/clinics/:id                  update hours, escalation number
POST   /api/clinics/:id/calendar/oauth   initiate OAuth flow (Google/Outlook)
GET    /api/clinics/:id/departments      list
POST   /api/clinics/:id/departments      create
POST   /api/clinics/:id/doctors          create doctor
POST   /api/clinics/:id/faq-documents    upload + trigger embedding job
GET    /api/clinics/:id/call-logs        paginated, filterable by outcome/date
GET    /api/clinics/:id/metrics          latency, escalation rate, booking completion (§success criteria)
```
Auth: Supabase Auth/Clerk session, scoped to `clinic_id` via row-level org membership — every route checks the authenticated user belongs to the `clinic_id` in the path, not just that they're logged in.

**Tenant isolation is not app-layer-only.** Relying solely on every query remembering to filter by `clinic_id` is one missed `WHERE` clause away from a cross-tenant PHI leak — a real risk in a solo, time-boxed build. Postgres row-level security (RLS) policies, keyed on a session-scoped `clinic_id`, sit underneath the application filtering as defense-in-depth: a forgotten filter fails closed instead of leaking another clinic's patient data. This is cheap to set up and should be in place before the pilot goes live, not added later.

### 6.2 Internal orchestrator interfaces (not HTTP — in-process/module boundaries within the LangGraph graph)
```
EscalationCheck(transcript_turn, call_context) -> { escalate: bool, confidence, matched_rule? }
IntentRouter(transcript_turn, call_context) -> Intent (Book|Reschedule|Cancel|FAQ|Unclear)
IdentityVerifier(name, phone_or_dob, clinic_id) -> { verified: bool, patient_id? }
BookingService.create(clinic_id, doctor_id, patient_id, start_time) -> { booking_id, ext_event_id } | ConflictError
CalendarAdapter.getAvailability(clinic_id, doctor_id, date_range) -> Slot[]
RAGQuery(clinic_id, question) -> { answer, source_doc_ids, confidence }
```
Keeping these as clean function boundaries (even though they run in-process) is what makes the LangGraph nodes testable independently of the live voice pipeline — the build order in the tech-stack doc already gets this right (text-only state machine before voice wiring); this interface list is what makes that staged approach actually work in practice.

---

## 7. Security & observability

### 7.1 AuthN/AuthZ
- **Dashboard:** Supabase Auth/Clerk session tokens; clinic-scoped RBAC (staff can edit their own clinic's config only — no cross-tenant access, enforced at the query layer via `clinic_id` filtering on every query, not just at the route layer)
- **Calendar OAuth tokens:** stored encrypted (pgcrypto column), never logged, refreshed server-side, never exposed to the frontend
- **No end-user auth on the phone side** — identity verification (name + phone/DOB match) is the authentication mechanism for touching an existing booking, which is a deliberately lighter bar than a password/token, appropriate for a phone channel where that's the realistic ceiling

### 7.2 Encryption
- At rest: `patients` PII columns via pgcrypto (per §4.2); calendar OAuth tokens encrypted
- In transit: TLS everywhere (Twilio, Deepgram, ElevenLabs, Groq, calendar APIs, Postgres connections all TLS by default on the chosen managed providers)

### 7.3 Vendor-side data retention (closing the gap the schema alone doesn't cover)
Section 4.2 structurally enforces "no symptom data stored" by giving `patients` no symptom column — but that guarantee only covers your own Postgres instance. It means nothing if Twilio call recording is left on by default, or if Deepgram/ElevenLabs retain request audio/transcripts under their standard logging policy — in that case the system is storing exactly the symptom content it promised the pilot clinic it wouldn't, just at the vendor layer instead of yours. This needs to be an explicit onboarding step, not an assumption: disable Twilio call recording, and set STT/TTS vendor retention to the shortest window available (zero-retention if the vendor offers it). The pilot clinic's sign-off (open risk #1 in the problem statement) should name this explicitly, since it's part of the actual privacy commitment being made to them.

### 7.4 Domain-specific guardrail (the actual security-relevant novelty here)
The escalation guardrail (§5.4) is this system's equivalent of a security control, even though it's framed as a clinical-safety feature — treat it with the same rigor as an auth boundary: tested, gated in CI, changes reviewed, false negatives tracked as incidents. The "no symptom data stored" design (§4.2) is the privacy-equivalent control — it's enforced structurally (no column exists) rather than by policy, which is the right pattern and worth naming explicitly as the reason it's trustworthy.

### 7.5 Secrets
Per-tenant secrets (calendar OAuth tokens) in encrypted Postgres columns, not a secrets manager — correct call from the tech-stack doc for one-pilot-clinic scale, restated. Global secrets (Deepgram/ElevenLabs/Groq/Twilio API keys) in the hosting platform's environment variable store (Fly.io/Railway/Vercel secrets), not committed, not in the repo.

### 7.6 Observability
- **Logging:** Sentry for errors/exceptions across both services. Structured logs (not just error logs) for every call: latency per turn, intent routed, escalation fired or not, outcome — this is what the success-criteria metrics (§1.2, and the problem statement's §7) are actually computed from, so the logging schema needs to support those queries from day one, not be retrofitted.
- **Metrics that matter operationally:** escalation rate (sudden drops are as concerning as the guardrail firing too much — a silent failure in the detection path would show up as escalation rate dropping to zero), p50/p95 latency, booking completion rate, cost per call (token usage + STT/TTS minutes, tagged per call in `call_logs`).
- **Alerting:** the one alert that must exist before go-live is "Twilio transfer to escalation number failed" (§5.2) — everything else can be dashboard-checked, but a failed escalation transfer is the one failure mode where a human needs to know immediately, not at next login.
- **Audit trail:** `call_logs` is itself the audit trail for the guardrail's decisions (escalated: true/false per call, with `matched_rule` from the keyword layer retained for that call) — sufficient for the clinician review of the red-flag list mentioned in the problem statement's open risks, without storing any symptom text itself.

---

## 8. Low-level design

### 8.1 LangGraph state machine shape
The core design decision, worth spelling out as an actual graph rather than prose:

```
Nodes: EscalationCheck, IntentRouter, IdentityGate, Book, Reschedule, Cancel, FAQ, Unclear, End

Edges:
  EVERY node -> EscalationCheck runs in parallel on every incoming turn
    EscalationCheck(escalate=true) -> Escalate (terminal, live transfer) -- preempts whatever was active
  Entry -> IntentRouter
  IntentRouter -> Book | FAQ                          (no identity gate needed)
  IntentRouter -> IdentityGate                          (for Reschedule/Cancel intent)
  IdentityGate(verified) -> Reschedule | Cancel
  IdentityGate(not verified, retries<2) -> IdentityGate (re-prompt)
  IdentityGate(not verified, retries>=2) -> Escalate
  IntentRouter -> Unclear (retries<2) -> IntentRouter
  Unclear(retries>=2) -> Escalate
  Book | Reschedule | Cancel | FAQ -> End | IntentRouter (multi-intent calls, e.g. "also, what are your hours")
```

**Why this shape, not a simpler linear flow:** the requirement that escalation preempts *any* active node (not just a branch at intent classification) is the one requirement that actually forces a graph rather than a simple if/elif dispatcher — this is the specific LLD justification for choosing LangGraph over a hand-rolled state machine, beyond just "it's a nice artifact to show later" (which the tech-stack doc mentions but doesn't fully justify on its own).

### 8.2 Key modules / responsibilities
- `CallSession` (class): holds per-call state — turn history, current node, identity-verification status, retry counters. One instance per active call, lives in the voice gateway process for the call's duration (per §2's statefulness note).
- `EscalationDetector`: wraps the two-layer check (§5.4) behind one interface so the keyword list and the fallback classifier model can be swapped/tuned independently of the graph logic that calls it.
- `CalendarAdapter` (interface) with `GoogleCalendarAdapter` / `OutlookCalendarAdapter` implementations — a straightforward Adapter pattern, justified because there are exactly two providers with genuinely different APIs and the orchestrator should not branch on provider type.
- `RAGService`: query embedding + Qdrant filter-by-`clinic_id` + answer synthesis, kept as one module so the FAQ confidence threshold (below which the system says "let me connect you with staff" rather than guessing) lives in one place.

### 8.3 One design pattern worth naming: fail-safe defaults over fail-open
Every ambiguous-failure branch in §5.2 defaults toward escalation or a safe stop, never toward silently proceeding as if things are fine. This isn't a formal pattern name so much as a stated design principle that should be checked in code review: when in doubt, the system routes toward a human, not toward guessing. Worth stating explicitly here because it's easy to lose under time pressure during the "get one real call working end-to-end" step (build-order step 5 in the tech-stack doc) if it isn't written down as a rule.

---

## 9. Trade-offs & alternatives considered

| Decision | Alternative considered | Why rejected |
|---|---|---|
| Modular monolith | Microservices per component (STT service, orchestrator service, calendar service) | Adds network hops and deployment complexity with no scaling payoff at low-tens-of-concurrent-calls scale; a solo dev pays this cost in velocity for the entire build with zero benefit until traffic is orders of magnitude higher |
| Groq/Llama for dialogue, second-tier model for escalation ambiguity | One frontier model (GPT-4-class) for everything | Cost-per-call is an explicit hard constraint; a single expensive model for every turn (most of which are routine booking/FAQ turns) would blow the budget for no accuracy gain on the 95% of turns that aren't safety-critical |
| Rule-based-first escalation detection | Pure LLM-based symptom classification | An LLM-only approach is a black box for the one decision that needs to be auditable against a named clinical guideline source and needs near-perfect, provably-tested recall; rules are inspectable, LLM judgment is the fallback for what rules miss, not the primary layer |
| Single Postgres, `tenant_id` column | Database-per-tenant | Only justified once compliance requirements demand physical isolation at real multi-tenant scale — premature for one pilot clinic and adds real ops burden a solo dev doesn't need yet |
| No Redis cache layer | Add caching for tenant config lookups | Solves a bottleneck that doesn't exist at this call volume; adds a moving part and a cache-invalidation problem for no measured benefit |
| Reduced-PHI footprint (name/phone/DOB only, no symptom storage), full HIPAA deferred | Build full HIPAA/BAA-compliant infra from day one | Explicitly a business/timeline trade-off already made in the problem statement, not re-litigated here — but worth noting the technical design (§4.2's "no column exists" pattern) is what makes the deferred-compliance posture actually defensible rather than just a promise |
| Single-region deployment | Multi-region active-active | One pilot clinic, one timezone, no realistic scenario where regional failover matters more than getting the guardrail right; this is the textbook premature-optimization trap the topic map warns about, called out explicitly rather than silently skipped |

---

## 10. Testing & delivery

- **Escalation red-flag test set:** the single most important test suite in this system (§5.4) — built from NHS 111/Manchester Triage source material, run in CI on every change touching the keyword list, the classifier prompt, or the graph's escalation edges. Recall regression fails the build; precision regression is a warning, not a blocker, matching the problem statement's own stated priority.
- **Unit tests:** each LangGraph node in isolation (IntentRouter, IdentityGate, Book, etc.) against mock transcripts — enabled directly by the build order's "text-only state machine first" step, since these nodes are pure functions over transcript + call state until the voice pipeline is wired in.
- **Integration tests:** calendar adapter against a sandbox Google Calendar / Outlook test account; booking idempotency under simulated retry-after-timeout.
- **Load/latency testing:** simulate the estimated peak (10–15 concurrent calls, §1.3) against the full voice pipeline before go-live, to actually pin the latency number the problem statement flags as still-open — this is the benchmarking pass both source docs defer, and it should happen before, not after, calling the build "done."
- **CI/CD:** straightforward pipeline (lint, unit tests, escalation-recall gate, deploy to staging, manual smoke test of one real call, deploy to prod) — no need for elaborate blue-green or canary infrastructure at one-pilot-clinic scale; a short maintenance window for deploys is an acceptable trade-off here, and pretending otherwise would be over-building for the stated constraints.
- **Rollback:** keep the previous Fly.io/Railway deploy one command away; Postgres migrations should be additive/backward-compatible during the pilot phase (no destructive schema changes without a maintenance window), since a mid-pilot rollback that breaks the schema would be a self-inflicted outage.

---

## 11. Sections considered and intentionally scoped out

Per the topic map, every section was considered; these are explicitly out of scope for v1, not silently dropped:
- **Sharding/partitioning:** irrelevant at single-tenant-pilot data volume.
- **Multi-leader/quorum replication:** single managed Postgres instance is sufficient; failover is the managed provider's job at this tier.
- **Message queues/event streaming:** the system has no async workload that needs one — calendar OAuth and FAQ embedding jobs are the only background work, and both are simple enough for a basic job runner (or even a direct synchronous call for the pilot's low volume) rather than a full queue.
- **API gateway as a separate component:** unnecessary indirection for two small services; Next.js API routes and the voice gateway's own routing are sufficient.
- **CDN/edge caching:** the admin dashboard is low-traffic and mostly authenticated; Vercel's default edge network for static assets is enough, no separate CDN decision needed.

---

*This document is the "how it's built" companion to the problem statement's "what" and the tech-stack doc's "with what." Next step per the tech-stack doc's build order: mock data + schema (§4.2 above is that schema), then the LangGraph state machine (§8.1) text-only, before touching any paid voice API.*
