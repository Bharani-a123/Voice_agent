"""Run all 4 migrations against Supabase in order."""
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.environ["SUPABASE_DB_URL"]

# ── Migration 001: Extensions ─────────────────────────────────
migration_001 = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
"""

# ── Migration 002: Tables ─────────────────────────────────────
migration_002 = open("db/migrations/002_tables.sql").read()

# ── Migration 003: Indexes ────────────────────────────────────
migration_003 = open("db/migrations/003_indexes.sql").read()

# ── Migration 004: RLS ────────────────────────────────────────
migration_004 = open("db/migrations/004_rls.sql").read()

migrations = [
    ("001 — Extensions",  migration_001),
    ("002 — Tables",      migration_002),
    ("003 — Indexes",     migration_003),
    ("004 — RLS",         migration_004),
]

print("Connecting to Supabase...")
conn = psycopg2.connect(DB_URL)
conn.autocommit = True

for name, sql in migrations:
    print(f"\nRunning migration {name}...", end=" ")
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print("✓ Done")
    except Exception as e:
        print(f"\n  ❌ FAILED: {e}")
        conn.close()
        raise SystemExit(1)

# ── Verify extensions installed ────────────────────────────────
print("\nVerifying extensions...")
with conn.cursor() as cur:
    cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto','btree_gist','uuid-ossp') ORDER BY extname")
    exts = [r[0] for r in cur.fetchall()]
    print("  Installed:", exts)

# ── Verify tables created ──────────────────────────────────────
print("\nVerifying tables...")
with conn.cursor() as cur:
    cur.execute("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """)
    tables = [r[0] for r in cur.fetchall()]
    expected = ['bookings','calendar_oauth_tokens','call_logs','clinics',
                'departments','doctors','faq_documents','patients']
    for t in expected:
        status = "✓" if t in tables else "❌ MISSING"
        print(f"  {status}  {t}")

conn.close()
print("\n✅ All migrations complete! Ready to run seed.py")
