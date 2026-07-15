-- ============================================================
-- Migration 001: Enable required extensions
-- Run this FIRST before any other migration
-- ============================================================

-- pgcrypto: for encrypting PII columns (name, phone, dob)
-- and for HMAC-based phone_hash used for indexed lookups
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- btree_gist: required for the range exclusion constraint
-- on bookings (prevents double-booking overlapping time slots)
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- uuid-ossp: for uuid_generate_v4() if needed
-- (Postgres 13+ has gen_random_uuid() built-in, but this is a safe fallback)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
