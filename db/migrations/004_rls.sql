-- ============================================================
-- Migration 004: Row-Level Security (RLS) Policies
-- Depends on: 002_tables.sql
--
-- WHY RLS:
-- Application-level filtering (WHERE clinic_id = ?) is one missed
-- clause away from a cross-tenant PHI leak. RLS sits underneath
-- the application as a second layer — a forgotten filter in app
-- code fails CLOSED (returns no rows) instead of leaking another
-- clinic's patient data.
--
-- HOW IT WORKS:
-- The application sets a session variable:
--   SET LOCAL app.current_clinic_id = '<clinic_uuid>';
-- Every RLS policy reads this variable and filters automatically.
-- If the variable is not set, access is denied (fail-closed).
--
-- IMPORTANT: Service-role connections (e.g. Supabase service_role key)
-- bypass RLS by design. NEVER use service_role key in client-facing code.
-- Use it only in trusted server-side code (voice gateway, admin API).
-- ============================================================


-- ─── Enable RLS on all tables ──────────────────────────────

ALTER TABLE clinics              ENABLE ROW LEVEL SECURITY;
ALTER TABLE departments          ENABLE ROW LEVEL SECURITY;
ALTER TABLE doctors              ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients             ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings             ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs            ENABLE ROW LEVEL SECURITY;
ALTER TABLE faq_documents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_oauth_tokens ENABLE ROW LEVEL SECURITY;


-- ─── Helper function: get current clinic_id from session ───
-- Returns NULL if the session variable is not set.
-- All RLS policies use this — if it returns NULL, no rows are returned.
CREATE OR REPLACE FUNCTION current_clinic_id()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(
        current_setting('app.current_clinic_id', TRUE),
        ''
    )::UUID
$$;

COMMENT ON FUNCTION current_clinic_id() IS
    'Returns the clinic_id set by the application for the current session. '
    'Used by all RLS policies. Returns NULL if not set, causing fail-closed behavior.';


-- ─── clinics ───────────────────────────────────────────────
-- A clinic can only see and modify its own row.
CREATE POLICY clinics_tenant_isolation ON clinics
    USING (id = current_clinic_id());


-- ─── departments ───────────────────────────────────────────
CREATE POLICY departments_tenant_isolation ON departments
    USING (clinic_id = current_clinic_id());


-- ─── doctors ───────────────────────────────────────────────
CREATE POLICY doctors_tenant_isolation ON doctors
    USING (clinic_id = current_clinic_id());


-- ─── patients ──────────────────────────────────────────────
-- PHI table — most critical to isolate.
CREATE POLICY patients_tenant_isolation ON patients
    USING (clinic_id = current_clinic_id());


-- ─── bookings ──────────────────────────────────────────────
CREATE POLICY bookings_tenant_isolation ON bookings
    USING (clinic_id = current_clinic_id());


-- ─── call_logs ─────────────────────────────────────────────
CREATE POLICY call_logs_tenant_isolation ON call_logs
    USING (clinic_id = current_clinic_id());


-- ─── faq_documents ─────────────────────────────────────────
CREATE POLICY faq_documents_tenant_isolation ON faq_documents
    USING (clinic_id = current_clinic_id());


-- ─── calendar_oauth_tokens ─────────────────────────────────
CREATE POLICY calendar_oauth_tokens_tenant_isolation ON calendar_oauth_tokens
    USING (clinic_id = current_clinic_id());


-- ─── updated_at trigger ────────────────────────────────────
-- Automatically keep updated_at in sync for tables that have it.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER clinics_updated_at
    BEFORE UPDATE ON clinics
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER bookings_updated_at
    BEFORE UPDATE ON bookings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER calendar_oauth_tokens_updated_at
    BEFORE UPDATE ON calendar_oauth_tokens
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
