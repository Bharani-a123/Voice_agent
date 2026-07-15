# MediCare Connect — Solution Architecture & Tech Stack (v1)

Built against the confirmed constraints: solo dev, several weeks, multi-tenant SaaS from day one, real Twilio number, tight API budget, Google/Outlook calendar integration, self-serve admin dashboard, one pilot clinic live in production.

---

## 1. High-level architecture

```
                         ┌─────────────────────────────┐
Caller ──(PSTN)──► Twilio│  Phone number per clinic     │
                         │  Media Streams (WebSocket)   │
                         └──────────────┬───────────────┘
                                        │ raw audio (μ-law, 8kHz)
                                        ▼
                         ┌─────────────────────────────┐
                         │  Voice Gateway Service        │
                         │  (Node/Python, WebSocket)     │
                         │  - Twilio ↔ STT ↔ orchestrator│
                         │  - Barge-in / interrupt logic │
                         └──────────────┬───────────────┘
                                        │ streaming text
                                        ▼
                         ┌─────────────────────────────┐
                         │  Deepgram (streaming STT)     │
                         └──────────────┬───────────────┘
                                        │ transcript chunks
                                        ▼
                         ┌─────────────────────────────┐
                         │  LangGraph Orchestrator       │
                         │  - Escalation guardrail (every│
                         │    turn, preempts all nodes)  │
                         │  - Intent routing              │
                         │  - Identity verification       │
                         │  - RAG (FAQ)                   │
                         │  - Booking/reschedule/cancel   │
                         └──────┬───────────────┬────────┘
                                │               │
                    ┌───────────▼──┐      ┌─────▼─────────┐
                    │ Postgres      │      │ Qdrant (RAG)   │
                    │ (tenant data, │      │ per-clinic FAQ │
                    │ bookings,     │      │ collections    │
                    │ identity —    │      └────────────────┘
                    │ encrypted)    │
                    └───────┬───────┘
                            │
                    ┌───────▼────────────┐
                    │ Google/Outlook       │
                    │ Calendar API per     │
                    │ clinic (availability │
                    │ + write bookings)    │
                    └──────────────────────┘
                                        │ response text
                                        ▼
                         ┌─────────────────────────────┐
                         │  ElevenLabs (streaming TTS)   │
                         └──────────────┬───────────────┘
                                        │ audio
                                        ▼
                                     Twilio ──► Caller

Escalation path (parallel, overrides everything):
  Guardrail fires → Voice Gateway triggers Twilio live transfer
  → clinic's configured nurse/staff number (from tenant config)
  → call event logged (escalated: true, no symptom text stored)

Admin dashboard (separate app):
  Clinic staff ──► Next.js dashboard ──► API layer ──► Postgres
  (self-serve signup, department/doctor/hours config, calendar OAuth
   connect, escalation number config, FAQ document upload)
```

---

## 2. Tech stack by layer

| Layer | Choice | Why this, given your constraints |
|---|---|---|
| **Telephony** | Twilio (Programmable Voice + Media Streams) | Only realistic option for real PSTN numbers + real-time audio streaming; pay-per-minute fits "tight budget" better than a fixed platform fee |
| **STT** | Deepgram (Nova streaming model) | Cheapest streaming STT with genuinely low latency; usage-based pricing, no minimum commitment — fits solo/tight-budget |
| **LLM (dialogue/intent)** | Groq-hosted Llama 3.x (8B or 70B depending on latency testing) | Fastest inference available today for open models; usage-based and cheap relative to GPT-4-class models. Use this for intent classification, slot-filling, FAQ answer generation |
| **Escalation classifier (safety-critical)** | Rule-based keyword/phrase match **first**, cheap classifier model as second pass — NOT the same fast dialogue model alone | This is the one place where you deliberately spend more (in latency or a second model call) for recall. A keyword net is nearly free and catches most cases; route anything ambiguous to a slightly stronger model call rather than trusting Groq/Llama's speed-tier model alone |
| **TTS** | ElevenLabs (Flash/Turbo streaming tier) | Best natural-sounding voice for a healthcare context; use their cheaper "Flash" latency-optimized tier rather than the highest-fidelity tier to control cost — tone still matters more here than in generic bots, but v1 doesn't need the top tier |
| **Orchestration** | LangGraph | Explicit graph structure matches your state machine directly — this is also your strongest artifact to show/explain later |
| **Vector DB (RAG)** | Qdrant (self-hosted, single small instance, or Qdrant Cloud free/starter tier) | Lightweight, supports per-clinic metadata filtering so one instance can serve all tenants (filter by `clinic_id`) instead of provisioning per-tenant infra — important for keeping multi-tenant cost low |
| **Relational DB** | Postgres (managed — e.g. Supabase or Neon free/starter tier) | Handles tenant config, bookings, identity records, escalation logs. Supabase/Neon give you a generous free tier plus built-in auth, which also helps the admin dashboard |
| **Calendar integration** | Google Calendar API + Microsoft Graph API (Outlook), OAuth per clinic | Confirmed requirement — clinics connect their existing calendar rather than you building/maintaining a scheduling system |
| **Admin dashboard frontend** | Next.js + Tailwind | Fast to build solo, good defaults, easy deploy to Vercel free/hobby tier for MVP traffic levels |
| **Admin dashboard backend / API** | Same Next.js app (API routes) or a lightweight FastAPI service if you want Python parity with the voice pipeline | Keep it as one deployable unit if possible — less ops overhead for a solo build |
| **Auth (dashboard)** | Supabase Auth or Clerk (free tier) | Multi-tenant user/org management out of the box — don't hand-roll this |
| **Voice Gateway service** | Python (FastAPI + websockets) or Node (fastify + ws) | Whichever you're faster in — this is the piece gluing Twilio Media Streams to Deepgram/LangGraph/ElevenLabs in real time, so pick based on your comfort with async/streaming code, not novelty |
| **Hosting (voice gateway + orchestrator)** | Fly.io or Railway | Both support long-lived WebSocket connections cheaply, which most serverless platforms (Vercel functions, Lambda) handle poorly for this exact workload — this matters more than it looks |
| **Hosting (admin dashboard)** | Vercel (free/hobby tier) | Standard for Next.js, effectively free at pilot-clinic scale |
| **Secrets/config per tenant** | Postgres table + encrypted columns (pgcrypto), not a secrets manager yet | A secrets manager (e.g. AWS Secrets Manager) is overkill and adds cost for one pilot clinic — revisit at multi-tenant scale |
| **Monitoring/logging** | Basic: Sentry (errors) + simple structured logs to your DB/log provider | You need latency and escalation-rate logging from day one per your success metrics — don't bolt this on later |

---

## 3. Multi-tenancy data model (lean version for one pilot clinic, designed to extend)

- Single Postgres database, `tenant_id` (clinic id) as a column on every table — not separate databases per tenant. Simplest to build solo, cheapest to run, and standard practice until you have dozens of clinics with compliance reasons to isolate physically.
- Core tables (illustrative, not exhaustive):
  - `clinics` — id, name, escalation_phone_number, calendar_provider, calendar_oauth_tokens (encrypted)
  - `departments` — id, clinic_id, name (clinic-configurable, not fixed)
  - `doctors` — id, clinic_id, department_id, name, calendar_id
  - `patients` — id, clinic_id, name, phone, dob (encrypted columns) — **no symptom/clinical fields**
  - `bookings` — id, clinic_id, patient_id, doctor_id, start_time, status
  - `call_logs` — id, clinic_id, call_sid, escalated (bool), latency_ms, outcome, timestamp — **no transcript of symptom content stored**
  - `faq_documents` — id, clinic_id, source_doc, embedded in Qdrant under `clinic_id` filter

This keeps the "no clinical data stored" commitment structurally enforced — there's simply no column for it, rather than relying on discipline to not log it.

---

## 4. Cost shape (directional, not exact — validate with a benchmarking pass)

| Component | Pricing model | Note |
|---|---|---|
| Twilio | Per-minute (inbound + Media Streams) | Biggest fixed-per-call cost, unavoidable |
| Deepgram | Per-minute streaming | Cheapest tier of the major STT vendors |
| Groq (Llama) | Per-token, very low relative to GPT-4-class | Main lever if cost-per-call runs high — trim prompt size before switching models |
| ElevenLabs | Per-character (Flash tier cheaper than default) | Second-biggest cost after Twilio; test Flash tier quality before committing |
| Qdrant / Postgres / Vercel / Fly.io | Free or starter tiers | Effectively $0–20/month at one-pilot-clinic scale |

Cost-per-call needs an actual benchmark once the pipeline is wired up — don't estimate further without real numbers, since STT/TTS pricing is usually the swing factor, not the LLM.

---

## 5. Build order (solo, several weeks)

1. **Mock data + schema** — Postgres schema above, seed one pilot clinic's departments/doctors/hours
2. **LangGraph state machine** — text-only first (no voice), test intent routing + escalation guardrail + booking logic against mock data
3. **Calendar integration** — Google Calendar OAuth + read/write for the pilot clinic
4. **RAG/FAQ** — Qdrant + pilot clinic's actual FAQ content
5. **Voice pipeline wiring** — Twilio Media Streams ↔ Deepgram ↔ LangGraph ↔ ElevenLabs, get one real call working end-to-end
6. **Escalation live-transfer** — wire the real Twilio transfer to the nurse number, test against your red-flag test set until recall is ~100%
7. **Admin dashboard** — self-serve signup/config, since the pilot clinic needs to configure itself, not have you hand-edit the DB
8. **Latency/cost benchmarking + success-metric logging** — pin the actual numbers from section 4 before calling this "done"

Steps 1–2 are the highest-leverage first move — everything downstream depends on the state machine being right, and it's the cheapest thing to iterate on since it needs no paid API calls yet.

---

*Pairs with `medicare-connect-problem-statement.md`. This is the "how" to that document's "what."*
