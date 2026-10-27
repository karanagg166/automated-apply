"""Google's documented HTTPS OAuth endpoints; never log upstream bodies or tokens."""

import asyncio
import base64
import hashlib
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from backend.app.integrations.token_store import ConnectionError

METADATA_SCOPE = "https://www.googleapis.com/auth/gmail.metadata"

SCOPES = frozenset(
    {
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        METADATA_SCOPE,
    }
)
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SEND_SCOPES = SCOPES | {SEND_SCOPE}
COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
COMPOSE_SCOPES = frozenset({"openid", "https://www.googleapis.com/auth/userinfo.email", COMPOSE_SCOPE})
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
READ_SCOPES = frozenset({"openid", "https://www.googleapis.com/auth/userinfo.email", READ_SCOPE})
ALLOWED_SCOPE_SETS = (SCOPES, SEND_SCOPES, COMPOSE_SCOPES, READ_SCOPES)

EMAIL_ALIASES = {"email": "https://www.googleapis.com/auth/userinfo.email"}


def normalized_scopes(raw):
    if not isinstance(raw, str):
        raise ConnectionError("missing_granted_scopes")
    return {EMAIL_ALIASES.get(s, s) for s in raw.split()}


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    access_token: str = Field(min_length=1, max_length=16384, repr=False)
    refresh_token: str | None = Field(
        default=None, min_length=1, max_length=16384, repr=False
    )
    token_type: str
    expires_in: StrictInt = Field(ge=1, le=86400)
    scope: str | None = None

    @field_validator("token_type")
    @classmethod
    def bearer(cls, value):
        if value.casefold() != "bearer":
            raise ValueError("invalid_token_type")
        return value


class GoogleOAuth:
    def __init__(self, settings, client=None):
        self.settings, self.client = settings, client

    def configured(self):
        return bool(
            self.settings.GMAIL_CLIENT_ID
            and self.settings.GMAIL_CLIENT_SECRET
            and self.settings.GMAIL_REDIRECT_URI
        )

    def authorization_url(self, state, verifier, expected_email, *, send=False, compose=False, read_body=False):
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": self.settings.GMAIL_CLIENT_ID,
                "redirect_uri": self.settings.GMAIL_REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(sorted(READ_SCOPES if read_body else COMPOSE_SCOPES if compose else SEND_SCOPES if send else SCOPES)),
                "state": state,
                "access_type": "offline",
                "prompt": "consent select_account",
                "login_hint": expected_email,
                "include_granted_scopes": "false",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    async def request(self, method, url, **kwargs):
        try:
            async with asyncio.timeout(20):
                if self.client:
                    response = await self.client.request(method, url, **kwargs)
                else:
                    async with httpx.AsyncClient(
                        timeout=15, follow_redirects=False
                    ) as client:
                        response = await client.request(method, url, **kwargs)
            if response.status_code != 200:
                # Do not expose Google error_description, response bodies or request URLs.
                code = "google_request_failed"
                if url.endswith("/token") and response.status_code == 400:
                    try:
                        if (
                            isinstance(response.json(), dict)
                            and response.json().get("error") == "invalid_grant"
                        ):
                            code = "credential_revoked_or_code_invalid"
                    except ValueError:
                        pass
                raise ConnectionError(code)
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                raise ConnectionError("invalid_google_response")
            return payload
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            if isinstance(exc, ConnectionError):
                raise
            raise ConnectionError("google_transport_or_response_error") from None

    async def exchange(self, code, verifier):
        return await self.request(
            "POST",
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.settings.GMAIL_CLIENT_ID,
                "client_secret": self.settings.GMAIL_CLIENT_SECRET,
                "redirect_uri": self.settings.GMAIL_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
        )

    async def refresh(self, refresh_token):
        return await self.request(
            "POST",
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.settings.GMAIL_CLIENT_ID,
                "client_secret": self.settings.GMAIL_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    async def identity(self, token):
        headers = {"Authorization": "Bearer " + token}
        identity = await self.request(
            "GET", "https://openidconnect.googleapis.com/v1/userinfo", headers=headers
        )
        if (
            not isinstance(identity.get("sub"), str)
            or not 1 <= len(identity["sub"]) <= 255
            or identity.get("email_verified") is not True
            or not isinstance(identity.get("email"), str)
        ):
            raise ConnectionError("identity_verification_failed")
        gmail = await self.request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers=headers,
        )
        if (
            not isinstance(gmail.get("emailAddress"), str)
            or gmail["emailAddress"].casefold() != identity["email"].casefold()
        ):
            raise ConnectionError("gmail_identity_mismatch")
        return identity["sub"], identity["email"].casefold()

    async def revoke(self, refresh_token):
        await self.request(
            "POST",
            "https://oauth2.googleapis.com/revoke",
            data={"token": refresh_token},
        )
