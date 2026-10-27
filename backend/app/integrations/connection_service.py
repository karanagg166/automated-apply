"""Single-owner account lifecycle. PostgreSQL locks serialize callback/refresh/disconnect."""

import hashlib
import secrets
from datetime import timedelta

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import get_settings
from backend.app.integrations.google_oauth import (
    ALLOWED_SCOPE_SETS,
    COMPOSE_SCOPES,
    METADATA_SCOPE,
    READ_SCOPE,
    READ_SCOPES,
    SCOPES,
    SEND_SCOPES,
    GoogleOAuth,
    TokenResponse,
    normalized_scopes,
)
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.connected_account import (
    ConnectedAccount,
    GmailReadAccount,
    GmailReadOAuthState,
    OAuthState,
)
from backend.app.models.discovery import now


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def compose_constraint_failure(error):
    """Inspect driver metadata only; never expose SQL, parameters or error text."""
    visited = set()
    while error is not None and id(error) not in visited:
        visited.add(id(error))
        if (getattr(error, "sqlstate", None) == "23514"
                and getattr(error, "constraint_name", None) == "oauth_states_authorization_mode_check"):
            return True
        error = getattr(error, "orig", None) or error.__cause__
    return False


def account_output(account):
    if not account:
        return {"status": "not_connected", "authorization_state": "not_connected", "send_capability": "not_connected", "account": None, "live_verified": False}
    return {
        "id": str(account.id),
        "status": account.status,
        "account_email": account.account_email,
        "google_subject": account.google_subject or None,
        "granted_scopes": account.granted_scopes,
        "workflow": account.workflow,
        "permissions": {"read_metadata": account.status == "connected" and bool(set(account.granted_scopes) & {METADATA_SCOPE, READ_SCOPE}),
                        "read_body": account.status == "connected" and set(account.granted_scopes) == READ_SCOPES,
                        "send": account.status == "connected" and account.workflow == "legacy" and set(account.granted_scopes) in (SEND_SCOPES, COMPOSE_SCOPES),
                        "modify": False},
        "connected_at": account.connected_at,
        "last_verified_at": account.last_verified_at,
        "last_refresh_at": account.last_refresh_at,
        "authorization_state": (
            account.status if account.status != "connected" else
            "send_authorized" if set(account.granted_scopes) == SEND_SCOPES else
            "compose_authorized" if set(account.granted_scopes) == COMPOSE_SCOPES else "readonly_connected" if set(account.granted_scopes) == READ_SCOPES else "metadata_connected"
        ),
        "send_capability": (
            account.status if account.status != "connected" else
            "send_authorized" if set(account.granted_scopes) == SEND_SCOPES else "send_authorization_required"
        ),
        "live_verified": account.status == "connected"
        and account.last_verified_at is not None,
    }


class ConnectionService:
    def __init__(self, session, settings=None, google=None, *, read_only=False, account_id=None):
        self.session, self.settings = session, settings or get_settings()
        self.google = google or GoogleOAuth(self.settings)
        self.read_only, self.account_id, self.expected_email = read_only, account_id, None

    async def lock(self):
        # Fixed namespace, transaction-scoped, shared by all backend processes.
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(text("SELECT pg_advisory_xact_lock(407006, 1)"))

    async def account(self, lock=False):
        model = GmailReadAccount if self.read_only else ConnectedAccount
        if self.read_only:
            from backend.app.integrations.gmail.schema import require_read_schema
            await require_read_schema(self.session, self.settings)
        stmt = (
            select(model)
            .where(model.provider == "gmail")
            .execution_options(populate_existing=True)
        )
        if self.account_id:
            stmt = stmt.where(model.id == self.account_id)
        elif self.read_only:
            if not self.expected_email:
                raise ConnectionError("gmail_account_id_required")
            stmt = stmt.where(model.account_email == self.expected_email)
        return await self.session.scalar(stmt.with_for_update() if lock else stmt)

    async def status(self):
        return account_output(await self.account()) | {"oauth_configured": self.google.configured(), "sending_enabled": self.settings.GMAIL_SENDING_ENABLED}

    async def start(self, expected_email, browser_secret, *, send=False, compose=False, read_body=False):
        if not self.google.configured():
            raise ConnectionError("google_oauth_not_configured")
        if self.read_only and (send or compose):
            raise ConnectionError("gmail_readonly_scope_required")
        if read_body and (not self.read_only or not self.settings.GMAIL_READ_BODY_REVIEWED):
            raise ConnectionError("gmail_body_access_review_required")
        store = TokenStore(self.settings)
        expected = expected_email if self.read_only else self.settings.GMAIL_EXPECTED_EMAIL or expected_email
        try:
            expected = str(TypeAdapter(EmailStr).validate_python(expected)).casefold()
        except ValidationError:
            raise ConnectionError("expected_secondary_email_required") from None
        if expected_email and expected_email.casefold() != expected:
            raise ConnectionError("expected_account_mismatch")
        self.expected_email = expected
        await self.lock()
        account = await self.account(lock=True)
        if send or compose:
            if not account or account.status not in {"connected", "reauthorization_required"} or not account.google_subject:
                raise ConnectionError("metadata_connection_required_before_upgrade")
            if expected != account.account_email:
                raise ConnectionError("wrong_google_account")
        elif account and account.status != "disconnected":
            if not (self.read_only and account.status == "reauthorization_required"):
                raise ConnectionError("disconnect_before_reconnecting")
        if not account:
            model = GmailReadAccount if self.read_only else ConnectedAccount
            account = model(
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
        state, verifier = ("read." if self.read_only else "") + secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        state_hash = digest(state)
        state_model = GmailReadOAuthState if self.read_only else OAuthState
        self.session.add(
            state_model(
                state_hash=state_hash,
                actor_id="owner",
                authorization_mode=("read_body" if read_body else "read_metadata") if self.read_only else "compose" if compose else "send" if send else "metadata",
                expected_subject=account.google_subject if send or compose or (self.read_only and account.google_subject) else None,
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
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if self.read_only and compose_constraint_failure(exc):
                raise ConnectionError("gmail_readonly_schema_update_required") from None
            if compose and compose_constraint_failure(exc):
                raise ConnectionError("gmail_compose_schema_update_required") from None
            raise
        return {
            "authorization_url": self.google.authorization_url(
                state, verifier, expected, **({"read_body": read_body} if self.read_only else {"compose": True} if compose else {"send": send})
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
        state_model = GmailReadOAuthState if state.startswith("read.") else OAuthState
        if state_model is GmailReadOAuthState:
            from backend.app.integrations.gmail.schema import require_read_schema
            await require_read_schema(self.session, self.settings)
        intent = (
            await self.session.execute(
                update(state_model)
                .where(
                    state_model.state_hash == digest(state),
                    state_model.browser_hash == digest(browser_secret),
                    state_model.provider == "gmail",
                    state_model.consumed_at.is_(None),
                    state_model.expires_at > now(),
                    state_model.redirect_uri == callback_uri,
                )
                .values(consumed_at=now())
                .returning(state_model)
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
        self.read_only = intent.authorization_mode in {"read_metadata", "read_body"}
        self.expected_email = intent.expected_email
        if intent.authorization_mode == "read_body" and not self.settings.GMAIL_READ_BODY_REVIEWED:
            raise ConnectionError("gmail_body_access_review_required")
        if scopes != (READ_SCOPES if intent.authorization_mode == "read_body" else COMPOSE_SCOPES if intent.authorization_mode == "compose" else SEND_SCOPES if intent.authorization_mode == "send" else SCOPES):
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
        if set(account.granted_scopes) not in ((SCOPES, READ_SCOPES) if self.read_only else ALLOWED_SCOPE_SETS):
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
            if scopes not in ((SCOPES, READ_SCOPES) if self.read_only else ALLOWED_SCOPE_SETS) or scopes != set(account.granted_scopes):
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
        state_model = GmailReadOAuthState if self.read_only else OAuthState
        await self.session.execute(
            update(state_model)
            .where(state_model.provider == "gmail", state_model.expected_email == account.account_email if account else False, state_model.consumed_at.is_(None))
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
