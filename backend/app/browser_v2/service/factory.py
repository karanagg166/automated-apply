"""Store / AI runtime / BrowserService construction from the project .env."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.app.browser_v2.manager import BraveBrowserManager
from backend.app.browser_v2.service.core import BrowserService
from backend.app.browser_v2.service.helpers import env_profile_overrides
from backend.app.browser_v2.service.registry import default_adapters
from backend.app.browser_v2.store import Store

if TYPE_CHECKING:
    from backend.app.ai_v2.runtime import AIRuntime


async def open_store(*, require_db: bool, env_file: str | None = None) -> tuple[Store, str]:
    """Postgres store; dry runs may fall back to memory before migration 004."""
    from backend.app.browser_v2.config import load_settings
    from backend.app.browser_v2.store import MemoryStore, PostgresStore

    try:
        return await PostgresStore.connect(load_settings(env_file)), "postgres"
    except Exception as exc:
        if require_db:
            raise RuntimeError(f"database_required_for_live_apply:{type(exc).__name__}:{exc}") from exc
        return MemoryStore(), f"memory ({type(exc).__name__}: {exc})"


async def build_ai(store: Store, env_file: str | None = None) -> AIRuntime | None:
    """Semantic cache + free LLM router on the store's connection (None if AI_V2_DISABLED)."""
    from backend.app.ai_v2.router import load_env
    from backend.app.ai_v2.runtime import AIRuntime, ai_disabled

    if ai_disabled():
        return None
    return await AIRuntime.for_store(store, env=load_env(env_file))


async def build_service(*, require_db: bool, env_file: str | None = None) -> tuple[BrowserService, str]:
    """Postgres-backed service; dry runs may fall back to memory before migration 004."""
    store, backend = await open_store(require_db=require_db, env_file=env_file)
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.auth import AutoLogin
    from backend.app.events_v2.bus import build_event_bus
    from backend.app.mail_v2.reader import MailEventStore, MailReadService

    env = load_env(env_file)
    connection = getattr(store, "connection", None)
    events = MailEventStore(connection if connection is not None and await MailEventStore.ready(connection) else None)
    reader = MailReadService.from_env(env, events=events)
    adapters = default_adapters(otp_provider=reader.fetch_recent_otp if reader.any_configured else None)
    service = BrowserService(BraveBrowserManager(), store, adapters, ai=await build_ai(store, env_file))
    service.mail_reader = reader
    profile, _ = await store.load_profile()
    owner_email = profile.get("email") if isinstance(profile.get("email"), str) else None
    if (env.get("AUTO_LOGIN_DISABLED") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        from backend.app.browser_v2.auth import ChainVault, EnvVault, KeychainVault

        service.auto_login = AutoLogin(ChainVault(EnvVault(env), KeychainVault()),
                                       mail_reader=reader if reader.any_configured else None, owner_email=owner_email)
    service.env_profile = env_profile_overrides(env)
    service.event_bus = build_event_bus(env, connection=connection)
    return service, backend
