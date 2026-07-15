"""
oauth_setup.py — Performs Google OAuth flow for development.
Spins up a temporary local web server at http://localhost:8080 to receive
the callback, exchange authorization_code for real tokens, encrypt them,
and insert them directly into Supabase calendar_oauth_tokens table.
"""

import os
import sys
import webbrowser
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Verify client credentials exist
CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
CLINIC_ID     = os.environ.get("PILOT_CLINIC_ID", "d72164a7-dd69-45c2-ac65-92c588b303a8")

if not CLIENT_ID or not CLIENT_SECRET:
    print("\n[ERROR] GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set in .env")
    print("Please follow Step 1 & 2 to create credentials and add them to your .env file.\n")
    sys.exit(1)

from agent.db_service import db

PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}"
AUTH_CODE = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Listens for the redirect from Google containing the auth code."""

    def do_GET(self):
        global AUTH_CODE
        query = urlparse(self.path).query
        params = parse_qs(query)

        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body style="font-family: sans-serif; text-align: center; margin-top: 100px; background-color: #0f172a; color: white;">
                    <h1 style="color: #22c55e;">Google OAuth Successful!</h1>
                    <p>You can close this tab and return to your terminal.</p>
                </body>
                </html>
            """)
        else:
            self.send_response(400)
            self.wfile.write(b"No authorization code returned.")


def get_auth_url() -> str:
    """Builds Google OAuth consent URL."""
    scope = "https://www.googleapis.com/auth/calendar"
    return (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope={scope}&"
        f"access_type=offline&"
        f"prompt=consent"
    )


def exchange_code_for_tokens(code: str) -> dict | None:
    """Exchanges authorization code for access_token and refresh_token."""
    try:
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri":  REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
            timeout=10
        )
        if resp.status_code != 200:
            print(f"\n[ERROR] Token exchange failed ({resp.status_code}): {resp.text}")
            return None
        return resp.json()
    except Exception as e:
        print(f"\n[ERROR] Exception during token exchange: {e}")
        return None


def save_tokens_to_db(tokens: dict):
    """Encrypts and saves tokens to Supabase calendar_oauth_tokens table."""
    access_token  = tokens["access_token"]
    refresh_token = tokens["refresh_token"]  # offline access guarantees this is returned
    expires_in    = tokens.get("expires_in", 3600)
    expiry        = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    try:
        with db._get_conn(CLINIC_ID) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO calendar_oauth_tokens (
                        clinic_id, provider, access_token_enc, refresh_token_enc, token_expiry
                    ) VALUES (
                        %s, 'google',
                        pgp_sym_encrypt(%s, %s),
                        pgp_sym_encrypt(%s, %s),
                        %s
                    )
                    ON CONFLICT (clinic_id, provider) DO UPDATE
                    SET access_token_enc = EXCLUDED.access_token_enc,
                        refresh_token_enc = EXCLUDED.refresh_token_enc,
                        token_expiry = EXCLUDED.token_expiry,
                        updated_at = NOW()
                """, (CLINIC_ID, access_token, db.enc_key, refresh_token, db.enc_key, expiry))
                conn.commit()
        print("\n[SUCCESS] OAuth tokens securely stored in Supabase database!")
        print(f"Expiry: {expiry.strftime('%Y-%m-%d %I:%M:%S %p UTC')}")
    except Exception as e:
        print(f"\n[ERROR] Failed to save tokens to database: {e}")


def main():
    print("=" * 60)
    print("MediCare Connect — Google OAuth Helper")
    print("=" * 60)
    print(f"Clinic ID  : {CLINIC_ID}")
    print(f"Redirect URI: {REDIRECT_URI}")
    print("-" * 60)

    # Start temporary local HTTP server
    server = HTTPServer(("localhost", PORT), OAuthCallbackHandler)
    print(f"1. Listening for redirect on http://localhost:{PORT}...")

    # Build auth URL and open in browser
    auth_url = get_auth_url()
    print("2. Opening Google login page in browser...")
    print(f"\n  --> CLICK THE LINK TO LOG IN: {auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for the callback
    print("3. Waiting for you to complete Google authorization...")
    server.handle_request()  # blocks until GET request containing 'code' arrives
    server.server_close()

    if not AUTH_CODE:
        print("\n[ERROR] Did not receive authorization code.")
        sys.exit(1)

    print("4. Exchanging code for access and refresh tokens...")
    tokens = exchange_code_for_tokens(AUTH_CODE)

    if not tokens:
        sys.exit(1)

    if "refresh_token" not in tokens:
        print("\n[WARNING] No refresh token returned. Google only sends this on the FIRST approval.")
        print("Go to your Google Account Settings -> Security -> Third-party apps -> Remove MediCare Connect")
        print("Then run this script again so Google displays the full approval screen.\n")

    print("5. Saving encrypted credentials to Supabase...")
    save_tokens_to_db(tokens)
    print("\nSetup complete! You can now run 'cli_test.py' to test real calendar booking.")
    print("=" * 60)


if __name__ == "__main__":
    main()
