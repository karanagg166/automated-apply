"""Single-owner account lifecycle. PostgreSQL locks serialize callback/refresh/disconnect."""

import hashlib
import secrets
from datetime import timedelta

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select, text, update

from backend.app.core.config import get_settings
from backend.app.integrations.google_oauth import (
    ALLOWED_SCOPE_SETS,
    COMPOSE_SCOPES,
    SCOPES,
    SEND_SCOPES,
    GoogleOAuth,
    TokenResponse,
    normalized_scopes,
)
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.connected_account import ConnectedAccount, OAuthState
from backend.app.models.discovery import now


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def account_output(account):
    if not account:
        return {"status": "not_connected", "authorization_state": "not_connected", "send_capability": "not_connected", "account": None, "live_verified": False}
    return {
        "id": str(account.id),
        "status": account.status,
        "account_email": account.account_email,
        "google_subject": account.google_subject or None,
        "granted_scopes": account.granted_scopes,
        "connected_at": account.connected_at,
        "last_verified_at": account.last_verified_at,
        "last_refresh_at": account.last_refresh_at,
        "authorization_state": (
            account.status if account.status != "connected" else
            "send_authorized" if set(account.granted_scopes) == SEND_SCOPES else
            "compose_authorized" if set(account.granted_scopes) == COMPOSE_SCOPES else "metadata_connected"
        ),
        "send_capability": (
            account.status if account.status != "connected" else
            "send_authorized" if set(account.granted_scopes) == SEND_SCOPES else "send_authorization_required"
        ),
        "live_verified": account.status == "connected"
        and account.last_verified_at is not None,
    }


class ConnectionService:
    def __init__(self, session, settings=None, google=None):
        self.session, self.settings = session, settings or get_settings()
        self.google = google or GoogleOAuth(self.settings)

    async def lock(self):
        # Fixed namespace, transaction-scoped, shared by all backend processes.
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(text("SELECT pg_advisory_xact_lock(407006, 1)"))

    async def account(self, lock=False):
        stmt = (
            select(ConnectedAccount)
            .where(ConnectedAccount.provider == "gmail")
            .execution_options(populate_existing=True)
        )
        return await self.session.scalar(stmt.with_for_update() if lock else stmt)

    async def status(self):
        return account_output(await self.account()) | {"oauth_configured": self.google.configured(), "sending_enabled": self.settings.GMAIL_SENDING_ENABLED}

    async def start(self, expected_email, browser_secret, *, send=False, compose=False):
        if not self.google.configured():
            raise ConnectionError("google_oauth_not_configured")
        store = TokenStore(self.settings)
        expected = self.settings.GMAIL_EXPECTED_EMAIL or expected_email
        try:
            expected = str(TypeAdapter(EmailStr).validate_python(expected)).casefold()
        except ValidationError:
            raise ConnectionError("expected_secondary_email_required") from None
        if expected_email and expected_email.casefold() != expected:
            raise ConnectionError("expected_account_mismatch")
        await self.lock()
        account = await self.account(lock=True)
        if send or compose:
            if not account or account.status not in {"connected", "reauthorization_required"} or not account.google_subject:
                raise ConnectionError("metadata_connection_required_before_upgrade")
            if expected != account.account_email:
                raise ConnectionError("wrong_google_account")
        elif account and account.status != "disconnected":
            raise ConnectionError("disconnect_before_reconnecting")
        if not account:
            account = ConnectedAccount(
                provider="gmail",
                google_subject="",
                account_email=expected,
                status="disconnected",
                token_generation=1,
                connected_at=now(),
            )
            self.session.add(account)
            await self.session.flush()
        account.token_generation += 1
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        state_hash = digest(state)
        self.session.add(
            OAuthState(
                state_hash=state_hash,
                actor_id="owner",
                authorization_mode="compose" if compose else "send" if send else "metadata",
                expected_subject=account.google_subject if send or compose else None,
                browser_hash=digest(browser_secret),
                expected_email=expected,
                encrypted_verifier=store.encrypt(verifier, state_hash),
                encryption_key_id=store.active,
                redirect_uri=self.settings.GMAIL_REDIRECT_URI,
                connection_generation=account.token_generation,
                expires_at=now()
                + timedelta(seconds=self.settings.OAUTH_STATE_TTL_SECONDS),
                created_at=now(),
            )
        )
        await self.session.commit()
        return {
            "authorization_url": self.google.authorization_url(
                state, verifier, expected, **({"compose": True} if compose else {"send": send})
            ),
            "expires_in": self.settings.OAUTH_STATE_TTL_SECONDS,
        }

    async def callback(
        self, state, browser_secret, callback_uri, code=None, error=None
    ):
        if (
            not state
            or not browser_secret
            or callback_uri != self.settings.GMAIL_REDIRECT_URI
        ):
            raise ConnectionError("invalid_oauth_state_or_redirect")
        store = TokenStore(self.settings)
        # Atomic consume is committed BEFORE code exchange. A failed callback cannot be replayed.
        intent = (
            await self.session.execute(
                update(OAuthState)
                .where(
                    OAuthState.state_hash == digest(state),
                    OAuthState.browser_hash == digest(browser_secret),
                    OAuthState.provider == "gmail",
                    OAuthState.consumed_at.is_(None),
                    OAuthState.expires_at > now(),
                    OAuthState.redirect_uri == callback_uri,
                )
                .values(consumed_at=now())
                .returning(OAuthState)
            )
        ).scalar_one_or_none()
        if intent is None:
            await self.session.rollback()
            raise ConnectionError("invalid_expired_or_replayed_state")
        verifier = store.decrypt(intent.encrypted_verifier, intent.state_hash)
        intent.encrypted_verifier = None
        await self.session.commit()
        if error:
            raise ConnectionError("consent_denied")
        if not code:
            raise ConnectionError("authorization_code_required")
        try:
            tokens = TokenResponse.model_validate(
                await self.google.exchange(code, verifier)
            )
        except ValidationError:
            raise ConnectionError("invalid_token_response") from None
        if not tokens.refresh_token:
            raise ConnectionError("refresh_token_required")
        scopes = normalized_scopes(tokens.scope)
        if scopes != (COMPOSE_SCOPES if intent.authorization_mode == "compose" else SEND_SCOPES if intent.authorization_mode == "send" else SCOPES):
            raise ConnectionError("unexpected_or_insufficient_scopes")
        subject, email = await self.google.identity(tokens.access_token)
        if email != intent.expected_email or (intent.expected_subject and subject != intent.expected_subject):
            raise ConnectionError("wrong_google_account")
        await self.lock()
        account = await self.account(lock=True)
        if (
            not account
            or (account.status == "connected" and intent.authorization_mode not in {"send", "compose"})
            or (intent.authorization_mode in {"send", "compose"} and (account.google_subject != subject or account.account_email != email or account.status == "disconnected"))
            or account.token_generation != intent.connection_generation
        ):
            raise ConnectionError("connection_intent_superseded")
        account.google_subject, account.account_email = subject, email
        purpose = str(account.id)
        account.encrypted_refresh_token = store.encrypt(
            tokens.refresh_token, purpose + ":refresh"
        )
        account.encrypted_access_token = store.encrypt(
            tokens.access_token, purpose + ":access"
        )
        account.encryption_key_id = store.active
        account.granted_scopes, account.status = sorted(scopes), "connected"
        account.connected_at = account.last_verified_at = now()
        account.token_expires_at = now() + timedelta(seconds=tokens.expires_in)
        account.disconnected_at = None
        account.token_generation += 1
        await self.session.commit()
        return account_output(account)

    async def access_token(self):
        if not self.google.configured():
            raise ConnectionError("google_oauth_not_configured")
        store = TokenStore(self.settings)
        await self.lock()
        account = await self.account(lock=True)
        if not account or account.status != "connected":
            raise ConnectionError("gmail_not_connected")
        if set(account.granted_scopes) not in ALLOWED_SCOPE_SETS:
            raise ConnectionError("unexpected_or_insufficient_scopes")
        if account.token_expires_at and account.token_expires_at.replace(
            tzinfo=now().tzinfo
        ) > now() + timedelta(seconds=60):
            token = store.decrypt(
                account.encrypted_access_token, str(account.id) + ":access"
            )
            await self.session.commit()
            return token
        try:
            refresh = store.decrypt(
                account.encrypted_refresh_token, str(account.id) + ":refresh"
            )
            tokens = TokenResponse.model_validate(await self.google.refresh(refresh))
            scopes = (
                normalized_scopes(tokens.scope)
                if tokens.scope is not None
                else set(account.granted_scopes)
            )
            if scopes not in ALLOWED_SCOPE_SETS or scopes != set(account.granted_scopes):
                raise ConnectionError("unexpected_or_insufficient_scopes")
            subject, email = await self.google.identity(tokens.access_token)
            if (subject, email) != (account.google_subject, account.account_email):
                raise ConnectionError("wrong_google_account")
        except (ConnectionError, ValidationError) as exc:
            account.status = "reauthorization_required"
            account.encrypted_access_token = None
            await self.session.commit()
            raise ConnectionError("gmail_reauthorization_required") from exc
        account.encrypted_access_token = store.encrypt(
            tokens.access_token, str(account.id) + ":access"
        )
        account.encrypted_refresh_token = store.encrypt(
            tokens.refresh_token or refresh, str(account.id) + ":refresh"
        )
        account.encryption_key_id = store.active
        account.token_generation += 1
        account.token_expires_at = now() + timedelta(seconds=tokens.expires_in)
        account.last_refresh_at = account.last_verified_at = now()
        await self.session.commit()
        return tokens.access_token

    async def disconnect(self):
        await self.lock()
        account = await self.account(lock=True)
        revocation = "not_needed"
        if account and account.encrypted_refresh_token:
            try:
                token = TokenStore(self.settings).decrypt(
                    account.encrypted_refresh_token, str(account.id) + ":refresh"
                )
                await self.google.revoke(token)
                revocation = "revoked"
            except ConnectionError:
                revocation = "unconfirmed_revoke_in_google_account_settings"
        if account:
            account.encrypted_refresh_token = account.encrypted_access_token = None
            account.encryption_key_id = None
            account.status, account.disconnected_at = "disconnected", now()
            account.token_generation += 1
        await self.session.execute(
            update(OAuthState)
            .where(OAuthState.provider == "gmail", OAuthState.consumed_at.is_(None))
            .values(consumed_at=now(), encrypted_verifier=None)
        )
        await self.session.commit()
        return {"status": "disconnected", "revocation": revocation}

    async def verify(self):
        token = await self.access_token()
        await self.lock()
        account = await self.account(lock=True)
        if not account or account.status != "connected":
            raise ConnectionError("gmail_not_connected")
        # A disconnect or reconnect may have occurred between access_token and this lock.
        current = TokenStore(self.settings).decrypt(
            account.encrypted_access_token, str(account.id) + ":access"
        )
        if current != token:
            raise ConnectionError("gmail_connection_changed_retry_verification")
        try:
            subject, email = await self.google.identity(token)
            if (subject, email) != (account.google_subject, account.account_email):
                raise ConnectionError("gmail_identity_mismatch")
        except ConnectionError:
            account.status, account.encrypted_access_token = (
                "reauthorization_required",
                None,
            )
            await self.session.commit()
            raise ConnectionError("gmail_reauthorization_required") from None
        account.last_verified_at = now()
        await self.session.commit()
