"""Gmail OAuth 2.0 Authorization Script for Job Pulse Agent.

This script executes a local OAuth 2.0 authorization code flow with offline access
to obtain a refresh token for reading job alert emails.

Scope requested: STRICTLY https://www.googleapis.com/auth/gmail.readonly
"""

import http.server
import os
import re
import socketserver
import sys
import urllib.parse
import webbrowser
from pathlib import Path
import httpx

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
REDIRECT_URI = "http://localhost:8080/callback"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def update_env_variable(key: str, value: str) -> None:
    """Safely update or add an environment variable in .env without modifying other lines."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    content = ENV_PATH.read_text(encoding="utf-8")
    pattern = rf"^{key}=.*$"
    replacement = f"{key}={value}"

    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += f"{replacement}\n"

    ENV_PATH.write_text(content, encoding="utf-8")


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    auth_code: str | None = None

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == "/callback":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            if "code" in query_params:
                OAuthCallbackHandler.auth_code = query_params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;text-align:center;padding:50px;'>"
                    b"<h2>&#10004; Authorization Successful!</h2>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                    b"</body></html>"
                )
            else:
                error = query_params.get("error", ["Unknown error"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Authorization failed: {error}".encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        # Suppress server request logging to avoid leaking URL params
        pass


def run_oauth_flow(client_id: str, client_secret: str) -> None:
    # 1. Build auth URL
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(auth_params)}"

    print("\n" + "=" * 70)
    print("Job Pulse Agent - Gmail OAuth Setup")
    print("Scope: gmail.readonly (minimum permissions - read only)")
    print("=" * 70)
    print("\nOpening browser for Google authorization...")
    print(f"If the browser does not open automatically, open this URL:\n\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # 2. Wait for callback on localhost:8080
    print("Waiting for OAuth callback on http://localhost:8080/callback ...")
    with socketserver.TCPServer(("localhost", 8080), OAuthCallbackHandler) as httpd:
        httpd.timeout = 180
        while OAuthCallbackHandler.auth_code is None:
            httpd.handle_request()

    code = OAuthCallbackHandler.auth_code
    if not code:
        print("Error: No authorization code received. Setup aborted.")
        sys.exit(1)

    print("Authorization code received. Exchanging for refresh token...")

    # 3. Exchange code for tokens
    resp = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15.0,
    )

    if resp.status_code != 200:
        print(f"Error exchanging authorization code: HTTP {resp.status_code}")
        sys.exit(1)

    token_data = resp.json()
    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")

    if not refresh_token:
        print("Warning: No refresh_token returned. Did you authorize with prompt=consent?")
        sys.exit(1)

    # 4. Verify connectivity using access token
    verify_resp = httpx.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    if verify_resp.status_code == 200:
        profile = verify_resp.json()
        email_address = profile.get("emailAddress", "verified")
        print(f"\nSUCCESS: Verified access to mailbox: {email_address}")
    else:
        print(f"\nWarning: Could not verify profile (HTTP {verify_resp.status_code}), but saving refresh token.")

    # 5. Persist to .env safely
    update_env_variable("GMAIL_CLIENT_ID", client_id)
    update_env_variable("GMAIL_CLIENT_SECRET", client_secret)
    update_env_variable("GMAIL_REFRESH_TOKEN", refresh_token)

    print("Gmail OAuth credentials saved securely to .env.")
    print("Scope confirmed: https://www.googleapis.com/auth/gmail.readonly")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    cid = sys.argv[1] if len(sys.argv) > 1 else os.getenv("GMAIL_CLIENT_ID", "").strip()
    csec = sys.argv[2] if len(sys.argv) > 2 else os.getenv("GMAIL_CLIENT_SECRET", "").strip()

    if not cid or not csec:
        print("\nUsage:")
        print("  backend/venv/bin/python backend/scripts/setup_gmail_oauth.py <CLIENT_ID> <CLIENT_SECRET>")
        print("\nOr populate GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env and run without arguments.")
        sys.exit(1)

    run_oauth_flow(cid, csec)
