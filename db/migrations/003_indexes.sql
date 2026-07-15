-- ============================================================
-- Migration 003: Indexes for performance
-- Depends on: 002_tables.sql
-- ============================================================

-- ─── clinics ───────────────────────────────────────────────
CREATE INDEX idx_clinics_status ON clinics(status);


-- ─── departments ───────────────────────────────────────────
CREATE INDEX idx_departments_clinic_id ON departments(clinic_id);


-- ─── doctors ───────────────────────────────────────────────
CREATE INDEX idx_doctors_clinic_id ON doctors(clinic_id);
CREATE INDEX idx_doctors_department_id ON doctors(department_id);
-- Only active doctors are queried during booking
CREATE INDEX idx_doctors_clinic_active ON doctors(clinic_id, active) WHERE active = TRUE;


-- ─── patients ──────────────────────────────────────────────
-- phone_hash is the primary lookup path during identity verification
-- (avoids decrypting every row to match a phone number)
CREATE INDEX idx_patients_clinic_phone_hash ON patients(clinic_id, phone_hash);


-- ─── bookings ──────────────────────────────────────────────
CREATE INDEX idx_bookings_clinic_id ON bookings(clinic_id);
CREATE INDEX idx_bookings_patient_id ON bookings(patient_id);
CREATE INDEX idx_bookings_doctor_id ON bookings(doctor_id);
-- Active bookings query (most common read path)
CREATE INDEX idx_bookings_doctor_active ON bookings(doctor_id, start_time)
    WHERE status IN ('pending', 'booked');
-- ext_event_id lookup for idempotency check on retries
CREATE INDEX idx_bookings_ext_event_id ON bookings(ext_event_id)
    WHERE ext_event_id IS NOT NULL;


-- ─── call_logs ─────────────────────────────────────────────
CREATE INDEX idx_call_logs_clinic_id ON call_logs(clinic_id);
CREATE INDEX idx_call_logs_clinic_started ON call_logs(clinic_id, started_at DESC);
-- Escalation monitoring query
CREATE INDEX idx_call_logs_escalated ON call_logs(clinic_id, escalated)
    WHERE escalated = TRUE;
-- call_sid lookup (Twilio webhook callbacks reference call_sid)
CREATE INDEX idx_call_logs_call_sid ON call_logs(call_sid);


-- ─── faq_documents ─────────────────────────────────────────
CREATE INDEX idx_faq_documents_clinic_id ON faq_documents(clinic_id);
-- Unindexed documents (pending embedding job)
CREATE INDEX idx_faq_documents_unindexed ON faq_documents(clinic_id)
    WHERE indexed_at IS NULL;


-- ─── calendar_oauth_tokens ─────────────────────────────────
CREATE INDEX idx_calendar_oauth_clinic ON calendar_oauth_tokens(clinic_id);
-- Token refresh check (find tokens expiring soon)
CREATE INDEX idx_calendar_oauth_expiry ON calendar_oauth_tokens(token_expiry);
