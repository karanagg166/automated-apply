"""Deprecated manual plaintext-token setup. Use the Phase 4A connection endpoints."""

import sys


def main():
    # Never read credentials from command-line arguments, open a browser or write .env.
    print("Manual Gmail refresh-token setup is retired. Configure server-side client credentials,")
    print("GMAIL_REDIRECT_URI and the OAuth encryption keyring, then use the authenticated")
    print("POST /api/v1/integrations/gmail/connect/start endpoint in the same browser.")
    print("See docs/gmail-oauth-connection.md. Existing legacy tokens are left untouched.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
