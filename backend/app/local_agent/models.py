"""PostgreSQL-backed policies, previews and polling state; no external execution."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base

Json = JSON().with_variant(JSONB, "postgresql")


class AgentPolicy(Base):
    __tablename__ = "agent_policies"
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    preferences: Mapped[dict] = mapped_column(Json, nullable=False)


class PolicyEvent(Base):
    __tablename__ = "agent_policy_events"
    id: Mapped[UUID] = mapped_column(GUID, primary_key=True, default=uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    preferences: Mapped[dict] = mapped_column(Json, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentOperation(Base):
    __tablename__ = "agent_operations"
    key: Mapped[str] = mapped_column(String(180), primary_key=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    command: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(Json, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TelegramState(Base):
    __tablename__ = "agent_telegram_state"
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    next_update_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    bot_id: Mapped[str | None] = mapped_column(String(40))
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(80))
    evidence_type: Mapped[str] = mapped_column(String(40), default="unverified", nullable=False)


class TelegramDelivery(Base):
    __tablename__ = "agent_telegram_deliveries"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reply: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
