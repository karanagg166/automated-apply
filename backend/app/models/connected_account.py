"""Durable single-owner connections and one-time OAuth intents."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base, TimestampMixin


class AccountFields:
    """Shared encrypted credential fields; legacy and read-only grants are isolated."""
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(30), default="gmail")
    google_subject: Mapped[str] = mapped_column(String(255))
    account_email: Mapped[str] = mapped_column(String(254))
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    encryption_key_id: Mapped[str | None] = mapped_column(String(64))
    granted_scopes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="connected")
    token_generation: Mapped[int] = mapped_column(Integer, default=1)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConnectedAccount(Base, TimestampMixin, AccountFields):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("provider", name="uq_connected_provider"),)
    workflow = "legacy"


class GmailReadAccount(Base, TimestampMixin, AccountFields):
    __tablename__ = "gmail_read_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "account_email", name="uq_gmail_read_email"),
        Index("uq_gmail_read_subject", "provider", "google_subject", unique=True,
              postgresql_where=text("google_subject <> ''"), sqlite_where=text("google_subject <> ''")),
    )
    workflow = "readonly"


class OAuthFields:
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), default="gmail")
    actor_id: Mapped[str] = mapped_column(String(64))
    browser_hash: Mapped[str] = mapped_column(String(64))
    expected_email: Mapped[str] = mapped_column(String(254))
    connection_generation: Mapped[int] = mapped_column(Integer)
    encrypted_verifier: Mapped[str | None] = mapped_column(Text)
    encryption_key_id: Mapped[str] = mapped_column(String(64))
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    authorization_mode: Mapped[str] = mapped_column(String(20), default="metadata")
    expected_subject: Mapped[str | None] = mapped_column(String(255))


class OAuthState(Base, OAuthFields):
    __tablename__ = "oauth_states"


class GmailReadOAuthState(Base, OAuthFields):
    __tablename__ = "gmail_read_oauth_states"
    __table_args__ = (CheckConstraint("authorization_mode IN ('read_metadata','read_body')", name="gmail_read_oauth_mode_check"),)
