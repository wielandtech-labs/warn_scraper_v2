#!/usr/bin/env python3
"""One-time OAuth 2.0 authorization for LinkedIn organization page posting.

Run interactively on your desktop to authorize and save tokens to
~/.warnindex/linkedin.json.

Setup (do these first):
  1. https://developer.linkedin.com/ → Create app
  2. Associate the app with the WARN Index LinkedIn page (you must be a page admin)
  3. Products tab → request "Community Management API"
  4. Auth tab → add redirect URL: http://localhost:8585/callback
  5. Note the Client ID and Client Secret from the Auth tab
  6. Find your organization ID: your page URL is linkedin.com/company/<id> or
     linkedin.com/company/<slug> — if it's a slug, the numeric ID is in the
     page source or via the API after auth.
"""
from __future__ import annotations

import http.server
import json
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from threading import Event

CONFIG = Path.home() / ".warnindex" / "linkedin.json"
REDIRECT_URI = "http://localhost:8585/callback"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
SCOPES = "w_organization_social r_organization_social openid profile"

auth_code: str | None = None
done = Event()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization complete. You can close this tab.")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Error: {params.get('error', ['unknown'])[0]}".encode())
        done.set()

    def log_message(self, *_args):
        pass


def main() -> None:
    print("LinkedIn OAuth setup for WARN Index page posting\n")
    client_id = input("Client ID: ").strip()
    client_secret = input("Client secret: ").strip()
    organization_id = input("Organization ID (numeric): ").strip()

    server = http.server.HTTPServer(("localhost", 8585), _Handler)

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    })
    url = f"{AUTH_URL}?{params}"
    print(f"\nOpening browser...\n{url}\n")
    webbrowser.open(url)

    while not done.is_set():
        server.handle_request()
    server.server_close()

    if not auth_code:
        print("Authorization failed.")
        sys.exit(1)

    print("Exchanging code for tokens...")
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        tokens = json.loads(resp.read())

    cfg = {
        "client_id": client_id,
        "client_secret": client_secret,
        "organization_id": organization_id,
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    CONFIG.chmod(0o600)

    expires = tokens.get("expires_in", "?")
    print(f"\nSaved to {CONFIG} (chmod 600)")
    print(f"Access token expires in {expires}s (~{int(expires)//86400}d)")
    if tokens.get("refresh_token"):
        print("Refresh token saved — linkedin_post.py will auto-refresh.")
    else:
        print("WARNING: No refresh token. You'll need to re-run this when the token expires.")
        print("(Refresh tokens require the 'Programmatic Refresh Tokens' product on your app.)")


if __name__ == "__main__":
    main()
