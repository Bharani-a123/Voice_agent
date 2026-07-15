# MediCare Connect

A multi-tenant, voice-based AI receptionist for multi-specialty clinics.

---

## Project Structure

```
Voice_agent/
├── db/
│   ├── migrations/
│   │   ├── 001_extensions.sql   ← Enable pgcrypto, btree_gist, uuid-ossp
│   │   ├── 002_tables.sql       ← All 8 core tables + enums + constraints
│   │   ├── 003_indexes.sql      ← Performance indexes
│   │   └── 004_rls.sql          ← Row-Level Security + updated_at triggers
│   ├── seed.py                  ← Seeds pilot clinic with test data
│   └── test_schema.py           ← Phase 1 test gate (7 automated checks)
├── .env.example                 ← Copy to .env and fill in values
├── requirements.txt             ← Python dependencies
└── README.md
```

---

## Phase 1 Setup — Step by Step

### Prerequisites
- Python 3.11+
- A Supabase project (free tier is fine)

---

### Step 1: Create Supabase Project

1. Go to [supabase.com](https://supabase.com) → New Project
2. Choose a region close to you (e.g. **ap-south-1** for India)
3. Note your **database password** — you'll need it for the connection string

---

### Step 2: Set Up Environment

```powershell
# Clone / open this project
cd "c:\Voice _agent"

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy env file and fill in values
copy .env.example .env
```

**Fill in `.env`:**
- `SUPABASE_DB_URL` — from Supabase Dashboard → Settings → Database → **URI** (use port **5432** for migrations)
- `APP_ENCRYPT_KEY` — generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
- `APP_HMAC_KEY` — generate a **different** key the same way

---

### Step 3: Run Migrations (in order)

Go to **Supabase Dashboard → SQL Editor** and run each file in order:

| Order | File | What it does |
|---|---|---|
| 1 | `db/migrations/001_extensions.sql` | Enables pgcrypto, btree_gist, uuid-ossp |
| 2 | `db/migrations/002_tables.sql` | Creates all 8 tables with constraints |
| 3 | `db/migrations/003_indexes.sql` | Adds performance indexes |
| 4 | `db/migrations/004_rls.sql` | Enables Row-Level Security |

> **Tip:** Copy each file's contents into Supabase SQL Editor → Run

---

### Step 4: Seed Pilot Data

```powershell
python db/seed.py
```

Expected output:
```
[1/7] Creating pilot clinic...      ✓ Greenfield Multi-Specialty Clinic
[2/7] Creating departments...       ✓ Cardiology  ✓ Orthopaedics
[3/7] Creating doctors...           ✓ Dr. Priya Sharma  ✓ Dr. Arjun Mehta  ✓ Dr. Kavitha Rajan
[4/7] Creating patients...          ✓ Ravi Kumar (encrypted)  ✓ Sunita Patel (encrypted)
[5/7] Creating bookings...          ✓ Booking 1 (active)  ✓ Booking 2 (cancelled)
[6/7] Creating call log...          ✓ outcome=booked, latency=1240ms
[7/7] Creating FAQ document...      ✓ greenfield_clinic_faq_v1.pdf

✅ Seed complete!  Clinic ID: <uuid>
```

Copy the `Clinic ID` into your `.env` as `PILOT_CLINIC_ID=<uuid>`

---

### Step 5: Run Phase 1 Test Gate

```powershell
python db/test_schema.py
```

Expected output:
```
✅ PASS  Clinic row found
✅ PASS  Clinic status = active
✅ PASS  Wrong clinic_id returns 0 patients
✅ PASS  Wrong clinic_id returns 0 bookings
✅ PASS  name_enc is not plaintext
✅ PASS  Decrypted name is correct
✅ PASS  Decrypted phone is E.164
✅ PASS  Decrypted DOB is a date
✅ PASS  phone_hash lookup finds correct patient
✅ PASS  Wrong phone hash finds nothing
✅ PASS  Overlapping slot is blocked by range exclusion
✅ PASS  Cancelled booking allows same slot to be rebooked
✅ PASS  2 departments seeded
✅ PASS  3 active doctors seeded

Results: 14/14 passed
🎉 Phase 1 test gate PASSED — ready for Phase 2!
```

---

## What Phase 1 Proves

| Guarantee | How it's enforced |
|---|---|
| No double-booking | Postgres range exclusion (`EXCLUDE USING gist`) |
| PII encrypted at rest | pgcrypto `pgp_sym_encrypt` on all 3 patient columns |
| Fast identity lookup without full decrypt | `phone_hash` HMAC index |
| Cross-tenant isolation | Row-Level Security on all 8 tables |
| No symptom/clinical data can be stored | The column does not exist |

---

## Next Phase

Once all 14 tests pass → **Phase 2: LangGraph Brain (text-only)**
The entire conversation logic (booking, FAQ, escalation guardrail) as a pure Python state machine — no voice APIs needed yet.
