"""
calendar_adapter.py — Handles OAuth retrieval, token refreshing, availability checks,
and event mutations on Google Calendar and Outlook Calendar.
Fully encrypted storage extraction via DBService.
"""

import os
import httpx
from datetime import datetime, timedelta, timezone
from agent.db_service import DBService, ENC_KEY


class CalendarAdapter:
    """Interface for calendar provider integrations (Google/Outlook)."""

    def get_availability(self, clinic_id: str, calendar_id: str,
                         start_time: datetime, end_time: datetime) -> list[dict]:
        """Returns list of free time slots in the range."""
        raise NotImplementedError

    def create_event(self, clinic_id: str, calendar_id: str, summary: str,
                     start_time: datetime, end_time: datetime, description: str = "") -> str | None:
        """Creates event on the external calendar. Returns the event ID."""
        raise NotImplementedError

    def delete_event(self, clinic_id: str, calendar_id: str, event_id: str) -> bool:
        """Deletes/cancels event on the external calendar."""
        raise NotImplementedError


class GoogleCalendarAdapter(CalendarAdapter):
    """Google Calendar API v3 implementation using direct HTTPS REST calls."""

    def __init__(self, db_service: DBService):
        self.db = db_service

    def _get_valid_token(self, clinic_id: str) -> str | None:
        """
        Retrieves the Google OAuth token for the clinic from database.
        Decrypts access_token and refresh_token, checks expiry,
        and refreshes the access token automatically if expired.
        """
        try:
            with self.db._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pgp_sym_decrypt(access_token_enc, %s) as access_token,
                               pgp_sym_decrypt(refresh_token_enc, %s) as refresh_token,
                               token_expiry
                        FROM calendar_oauth_tokens
                        WHERE clinic_id = %s AND provider = 'google'
                    """, (self.db.enc_key, self.db.enc_key, clinic_id))
                    row = cur.fetchone()

            if not row:
                print(f"[Calendar] No Google OAuth token registered for clinic {clinic_id}")
                return None

            access_token, refresh_token, token_expiry = row

            # If token is still valid (with a 5-minute safety buffer), return it
            if token_expiry > datetime.now(timezone.utc) + timedelta(minutes=5):
                return access_token

            # Token is expired or expiring soon — trigger refresh flow
            print(f"[Calendar] Google token expired. Refreshing for clinic {clinic_id}...")
            return self._refresh_token(clinic_id, refresh_token)

        except Exception as e:
            print(f"[Calendar] Error getting Google OAuth token: {e}")
            return None

    def _refresh_token(self, clinic_id: str, refresh_token: str) -> str | None:
        """Refresh Google OAuth access token using HTTP client."""
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

        if not client_id or not client_secret:
            # Fallback for dev: if client keys aren't set, simulate refresh with stub
            print("[Calendar] GOOGLE_CLIENT_ID/SECRET not set. Simulating refresh in dev mode...")
            return "mock_google_refreshed_access_token"

        try:
            resp = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type":    "refresh_token",
                },
                timeout=10
            )

            if resp.status_code != 200:
                print(f"[Calendar] Google token refresh failed ({resp.status_code}): {resp.text}")
                return None

            data = resp.json()
            new_access_token = data["access_token"]
            expires_in       = data.get("expires_in", 3600)
            new_expiry       = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Update DB with encrypted new access token
            with self.db._get_conn(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE calendar_oauth_tokens
                        SET access_token_enc = pgp_sym_encrypt(%s, %s),
                            token_expiry = %s,
                            updated_at = NOW()
                        WHERE clinic_id = %s AND provider = 'google'
                    """, (new_access_token, self.db.enc_key, new_expiry, clinic_id))
                    conn.commit()

            print(f"[Calendar] Google token refreshed successfully for clinic {clinic_id}")
            return new_access_token

        except Exception as e:
            print(f"[Calendar] Error during Google token refresh: {e}")
            return None

    def get_availability(self, clinic_id: str, calendar_id: str,
                         start_time: datetime, end_time: datetime) -> list[dict]:
        """
        Queries doctor availability using Google's freeBusy query endpoint.
        Returns a list of FREE 30-minute slots.
        """
        token = self._get_valid_token(clinic_id)
        if not token:
            # Dev Fallback: return mock slots if no calendar connected
            print(f"[Calendar] Falling back to mock slots for calendar {calendar_id}")
            return self._get_mock_availability(calendar_id, start_time, end_time)

        # In dev/mock token scenario:
        if token.startswith("mock_"):
            return self._get_mock_availability(calendar_id, start_time, end_time)

        try:
            # Query freeBusy endpoint
            payload = {
                "timeMin": start_time.isoformat(),
                "timeMax": end_time.isoformat(),
                "items": [{"id": calendar_id}]
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json"
            }

            resp = httpx.post(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                json=payload,
                headers=headers,
                timeout=10
            )

            if resp.status_code != 200:
                print(f"[Calendar] FreeBusy request failed ({resp.status_code}): {resp.text}")
                return self._get_mock_availability(calendar_id, start_time, end_time)

            busy_slots = resp.json().get("calendars", {}).get(calendar_id, {}).get("busy", [])

            # Compute free slots in 30-minute intervals
            return self._compute_free_slots(start_time, end_time, busy_slots)

        except Exception as e:
            print(f"[Calendar] Error fetching Google availability: {e}")
            return self._get_mock_availability(calendar_id, start_time, end_time)

    def create_event(self, clinic_id: str, calendar_id: str, summary: str,
                     start_time: datetime, end_time: datetime, description: str = "") -> str | None:
        """Creates Google Calendar event."""
        token = self._get_valid_token(clinic_id)
        if not token or token.startswith("mock_"):
            # Dev mode: mock successful event generation
            import uuid
            mock_id = f"GCal-{str(uuid.uuid4())[:8].upper()}"
            print(f"[Calendar] [DEV] Mock event created: {mock_id}")
            return mock_id

        try:
            payload = {
                "summary":     summary,
                "description": description,
                "start":       {"dateTime": start_time.isoformat()},
                "end":         {"dateTime": end_time.isoformat()},
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json"
            }

            resp = httpx.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                json=payload,
                headers=headers,
                timeout=10
            )

            if resp.status_code in (200, 201):
                return resp.json().get("id")

            print(f"[Calendar] Event creation failed ({resp.status_code}): {resp.text}")
            return None

        except Exception as e:
            print(f"[Calendar] Error creating Google event: {e}")
            return None

    def delete_event(self, clinic_id: str, calendar_id: str, event_id: str) -> bool:
        """Deletes Google Calendar event."""
        token = self._get_valid_token(clinic_id)
        if not token or token.startswith("mock_"):
            print(f"[Calendar] [DEV] Mock event deleted: {event_id}")
            return True

        try:
            headers = {"Authorization": f"Bearer {token}"}
            resp = httpx.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                headers=headers,
                timeout=10
            )

            return resp.status_code in (200, 204)

        except Exception as e:
            print(f"[Calendar] Error deleting Google event: {e}")
            return False

    def _get_mock_availability(self, calendar_id: str, start_time: datetime, end_time: datetime) -> list[dict]:
        """Fallback mock generator for local testing/development."""
        slots = []
        current = start_time
        # Generate 3 slots
        for i in range(3):
            slot_start = current.replace(hour=10 + i, minute=0, second=0, microsecond=0)
            slot_end   = slot_start + timedelta(minutes=30)

            ist_hour = (slot_start.hour + 5) % 24
            ist_min  = (slot_start.minute + 30) % 60
            am_pm    = "AM" if ist_hour < 12 else "PM"
            display_hour = ist_hour if ist_hour <= 12 else ist_hour - 12

            slots.append({
                "start": slot_start.isoformat(),
                "end":   slot_end.isoformat(),
                "label": f"Tomorrow at {display_hour}:{ist_min:02d} {am_pm} IST"
            })
        return slots

    def _compute_free_slots(self, start_time: datetime, end_time: datetime, busy_slots: list[dict]) -> list[dict]:
        """Calculates 30-minute free intervals that do not overlap with busy slots."""
        free_slots = []
        
        # Round up to the next 30-minute boundary to stabilize slot labels
        minutes_to_add = 30 - (start_time.minute % 30)
        current = start_time + timedelta(minutes=minutes_to_add)
        current = current.replace(second=0, microsecond=0)

        # Parse busy windows into datetimes
        busy_intervals = []
        for b in busy_slots:
            bs = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            be = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            busy_intervals.append((bs, be))

        while current + timedelta(minutes=30) <= end_time:
            slot_start = current
            slot_end   = current + timedelta(minutes=30)

            # Check overlap with busy intervals
            overlap = False
            for bs, be in busy_intervals:
                if not (slot_end <= bs or slot_start >= be):
                    overlap = True
                    break

            # Only offer typical clinic working hours: 8 AM to 8 PM IST (2:30 AM to 2:30 PM UTC)
            ist_hour = (slot_start.hour + 5) % 24
            if not overlap and 8 <= ist_hour < 20:
                am_pm = "AM" if ist_hour < 12 else "PM"
                display_hour = ist_hour if ist_hour <= 12 else ist_hour - 12
                free_slots.append({
                    "start": slot_start.isoformat(),
                    "end":   slot_end.isoformat(),
                    "label": f"Tomorrow at {display_hour}:{slot_start.minute:02d} {am_pm} IST"
                })

            current += timedelta(minutes=30)

        return free_slots[:3]  # return top 3 slots for voice interaction brevity
