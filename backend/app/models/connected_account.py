"""Durable single-owner connections and one-time OAuth intents."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base, TimestampMixin


class ConnectedAccount(Base, TimestampMixin):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("provider", name="uq_connected_provider"),)
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


class OAuthState(Base):
    __tablename__ = "oauth_states"
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
