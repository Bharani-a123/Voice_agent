-- ============================================================
-- Migration 002: Create all core tables
-- Depends on: 001_extensions.sql
-- ============================================================


-- ─────────────────────────────────────────────
-- ENUM TYPES
-- ─────────────────────────────────────────────

CREATE TYPE calendar_provider_enum AS ENUM ('google', 'outlook');

CREATE TYPE clinic_status_enum AS ENUM ('onboarding', 'active', 'suspended');

CREATE TYPE booking_status_enum AS ENUM (
    'pending',        -- slot reserved in our DB, calendar write in progress
    'booked',         -- calendar event confirmed
    'rescheduled',    -- moved to a new slot
    'cancelled',      -- cancelled by patient
    'failed'          -- calendar write failed, must not be shown as confirmed
);

CREATE TYPE call_outcome_enum AS ENUM (
    'booked',
    'rescheduled',
    'cancelled',
    'faq_answered',
    'escalated',
    'abandoned',
    'unclear_timeout'
);


-- ─────────────────────────────────────────────
-- TABLE: clinics
-- Root tenant table. Every other table joins back here via clinic_id.
-- ─────────────────────────────────────────────
CREATE TABLE clinics (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL,
    timezone                TEXT NOT NULL DEFAULT 'UTC',   -- IANA tz, e.g. 'Asia/Kolkata'
    escalation_phone_e164   TEXT NOT NULL,                 -- E.164 format, e.g. '+911234567890'
    calendar_provider       calendar_provider_enum,        -- null until OAuth connected
    status                  clinic_status_enum NOT NULL DEFAULT 'onboarding',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT clinics_phone_format CHECK (escalation_phone_e164 ~ '^\+[1-9]\d{6,14}$')
);

COMMENT ON TABLE clinics IS 'One row per tenant (clinic). Root of all multi-tenant data.';
COMMENT ON COLUMN clinics.escalation_phone_e164 IS 'The real human nurse/staff number to transfer urgent calls to.';


-- ─────────────────────────────────────────────
-- TABLE: calendar_oauth_tokens
-- Stores OAuth tokens per clinic, fully encrypted.
-- Intentionally separate from clinics table so tokens
-- are never accidentally included in SELECT * queries.
-- ─────────────────────────────────────────────
CREATE TABLE calendar_oauth_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    provider        calendar_provider_enum NOT NULL,
    -- access_token and refresh_token are encrypted with pgcrypto
    -- Use pgp_sym_encrypt(token_text, app_secret_key) to write
    -- Use pgp_sym_decrypt(token_bytes, app_secret_key) to read
    access_token_enc    BYTEA NOT NULL,
    refresh_token_enc   BYTEA NOT NULL,
    token_expiry        TIMESTAMPTZ NOT NULL,
    scope               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(clinic_id, provider)  -- one token per provider per clinic
);

COMMENT ON TABLE calendar_oauth_tokens IS 'Encrypted OAuth tokens per clinic. Never log or expose these columns.';


-- ─────────────────────────────────────────────
-- TABLE: departments
-- Clinic-configurable. Not a fixed global list — each clinic defines its own.
-- ─────────────────────────────────────────────
CREATE TABLE departments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id   UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(clinic_id, name)  -- no duplicate department names within a clinic
);

COMMENT ON TABLE departments IS 'Clinic-defined departments (e.g. Cardiology, Ortho). Not a fixed global list.';


-- ─────────────────────────────────────────────
-- TABLE: doctors
-- ─────────────────────────────────────────────
CREATE TABLE doctors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    department_id   UUID NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
    name            TEXT NOT NULL,
    -- calendar_id is the external calendar resource ID (e.g. Google Calendar resource ID)
    -- used by the CalendarAdapter to query and write events for this doctor
    calendar_id     TEXT NOT NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(clinic_id, calendar_id)  -- one calendar resource per doctor per clinic
);

COMMENT ON TABLE doctors IS 'Doctors per clinic, each linked to an external calendar resource.';


-- ─────────────────────────────────────────────
-- TABLE: patients
-- Stores ONLY: name, phone, DOB — all encrypted.
-- NO symptom, clinical, or diagnosis data — by design.
-- This column set is structurally enforced, not just policy.
-- ─────────────────────────────────────────────
CREATE TABLE patients (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id   UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,

    -- PII columns: encrypted at rest using pgcrypto
    -- Write: pgp_sym_encrypt(value::text, app_secret_key)
    -- Read:  pgp_sym_decrypt(column, app_secret_key)
    name_enc    BYTEA NOT NULL,
    phone_enc   BYTEA NOT NULL,
    dob_enc     BYTEA NOT NULL,

    -- phone_hash: HMAC of the phone number for indexed lookup during identity verification
    -- This allows "WHERE phone_hash = hmac(input_phone, hmac_key, 'sha256')"
    -- without decrypting every row. NOT the same key as the encryption key.
    -- This hash is deterministic but NOT reversible.
    phone_hash  TEXT NOT NULL,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- phone_hash must be unique per clinic (same patient, one record per clinic)
    UNIQUE(clinic_id, phone_hash)

    -- DELIBERATELY NO: symptom, diagnosis, clinical_notes, medical_history columns
    -- The column does not exist = the data cannot be accidentally stored
);

COMMENT ON TABLE patients IS 'Patient identity only (name/phone/DOB encrypted). No clinical data, by design.';
COMMENT ON COLUMN patients.phone_hash IS 'HMAC of phone number for indexed lookup. Not reversible. Use a separate HMAC key from the encryption key.';


-- ─────────────────────────────────────────────
-- TABLE: bookings
-- ─────────────────────────────────────────────
CREATE TABLE bookings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
    doctor_id       UUID NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    status          booking_status_enum NOT NULL DEFAULT 'pending',
    -- ext_event_id: the calendar provider's event ID
    -- Used as an idempotency key: if a retry fires after an uncertain first attempt,
    -- check for an existing event with this id before creating a duplicate.
    ext_event_id    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT bookings_time_order CHECK (end_time > start_time),

    -- DOUBLE-BOOKING GUARD (the critical constraint):
    -- Prevents two bookings for the same doctor with overlapping time ranges.
    -- A plain UNIQUE(doctor_id, start_time) only blocks identical start times —
    -- two bookings at 10:00-10:30 and 10:15-10:45 would both pass that check.
    -- This range exclusion constraint catches overlapping-but-different-start-time cases.
    -- Only applies to active bookings (pending/booked) — not rescheduled/cancelled/failed.
    -- Requires btree_gist extension (enabled in 001_extensions.sql).
    EXCLUDE USING gist (
        doctor_id WITH =,
        tstzrange(start_time, end_time) WITH &&
    ) WHERE (status IN ('pending', 'booked'))
);

COMMENT ON TABLE bookings IS 'Appointment bookings. Range exclusion constraint prevents double-booking.';
COMMENT ON COLUMN bookings.ext_event_id IS 'Calendar provider event ID. Idempotency key for retries.';
COMMENT ON COLUMN bookings.status IS 'pending=slot reserved; booked=calendar confirmed; failed=calendar write failed, do not show as confirmed.';


-- ─────────────────────────────────────────────
-- TABLE: call_logs
-- Audit trail for every call. No transcript, no symptom text.
-- ─────────────────────────────────────────────
CREATE TABLE call_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    call_sid        TEXT NOT NULL,           -- Twilio CallSid, unique per call
    escalated       BOOLEAN NOT NULL DEFAULT FALSE,
    -- matched_rule: the keyword/rule that triggered escalation (if escalated=true)
    -- This is the rule NAME (e.g. 'chest_pain_keyword'), NOT the patient's words
    matched_rule    TEXT,
    outcome         call_outcome_enum,
    latency_ms_p50  INT,                     -- median response latency for this call
    turn_count      INT NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,

    -- NO: transcript, symptom_text, clinical_content — structurally absent
    UNIQUE(call_sid)  -- one log row per Twilio call
);

COMMENT ON TABLE call_logs IS 'Per-call audit log. No transcript or symptom content stored — only outcome flags.';
COMMENT ON COLUMN call_logs.matched_rule IS 'Rule name that triggered escalation, not the patient spoken words.';


-- ─────────────────────────────────────────────
-- TABLE: faq_documents
-- Tracks uploaded FAQ documents per clinic.
-- Actual content lives in Qdrant (vector DB), referenced by qdrant_ids.
-- ─────────────────────────────────────────────
CREATE TABLE faq_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,           -- original filename or document title
    -- qdrant_ids: array of chunk IDs stored in Qdrant for this document
    -- If Qdrant is lost, re-embed from source_name/source content
    -- Qdrant is a rebuildable cache, NOT a source of truth
    qdrant_ids      TEXT[] NOT NULL DEFAULT '{}',
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    indexed_at      TIMESTAMPTZ,             -- null until embedding job completes

    UNIQUE(clinic_id, source_name)
);

COMMENT ON TABLE faq_documents IS 'FAQ document registry per clinic. Actual embeddings are in Qdrant.';
