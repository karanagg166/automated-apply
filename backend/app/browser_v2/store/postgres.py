"""PostgresStore: one asyncpg connection, composed from per-domain repository mixins."""

from __future__ import annotations

from backend.app.browser_v2.store.analytics_repo import AnalyticsRepo
from backend.app.browser_v2.store.applications_repo import ApplicationsRepo
from backend.app.browser_v2.store.audit_repo import AuditRepo
from backend.app.browser_v2.store.base import PostgresBase
from backend.app.browser_v2.store.conversation_repo import ConversationRepo
from backend.app.browser_v2.store.discovery_repo import DiscoveryRepo
from backend.app.browser_v2.store.drafts_repo import DraftsRepo
from backend.app.browser_v2.store.hitl_repo import HitlRepo
from backend.app.browser_v2.store.owner_queue_repo import OwnerQueueRepo
from backend.app.browser_v2.store.profile_repo import ProfileRepo
from backend.app.browser_v2.store.rules_repo import RulesRepo
from backend.app.browser_v2.store.watcher_repo import WatcherRepo


class PostgresStore(OwnerQueueRepo, DiscoveryRepo, ApplicationsRepo, RulesRepo, HitlRepo, ProfileRepo, DraftsRepo,
                    WatcherRepo, AuditRepo, ConversationRepo, AnalyticsRepo, PostgresBase):
    pass
