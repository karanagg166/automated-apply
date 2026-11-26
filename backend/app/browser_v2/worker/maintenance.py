"""Worker mixin: Phase 6A/8 housekeeping (mail watchers, HITL expiry, nightly digest)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.reports import (
    DECAY_EVERY_SEC,
    HITL_EXPIRY_EVERY_SEC,
    logger,
)


class MaintenanceMixin(WorkerLoop):
    # --- Phase 6A: housekeeping (mail watchers + nightly digest) ----------------------------
    async def housekeeping(self) -> None:
        now = self.clock()
        reader = self.mail_reader
        if reader is not None and getattr(reader, "any_configured", False) and (
                self.last_mail_scan is None
                or (now - self.last_mail_scan).total_seconds() >= self.mail_scan_interval_sec):
            self.last_mail_scan = now
            try:
                replies = await reader.scan_recruiter_replies(self.store, notify=self.notify)
                publish = getattr(self.service, "publish", None)
                for alert in replies.alerts:
                    if publish is not None:
                        await publish("mail.recruiter_reply", {"alert": alert[:200]})
                alerts = await reader.scan_job_alert_emails(self.store)
                self.housekeeping_log.append({"mail_scan": now.isoformat(), "replies": replies.new_events,
                                              "alert_jobs": alerts.discovered, "tier": replies.tier})
            except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
                logger.warning("mail watcher failed: %s", type(exc).__name__)
        await self.expire_hitl(now)
        await self.decay_priorities(now)
        await self.run_profile_sync()
        await self.send_digest(now, reader)
        del self.housekeeping_log[:-50]

    async def expire_hitl(self, now: datetime) -> None:
        """Phase 8: stale HITL requests expire (OTP 30 min .. QUESTION 7 days); never blocks."""
        if self.last_hitl_expiry is not None and (now - self.last_hitl_expiry).total_seconds() < HITL_EXPIRY_EVERY_SEC:
            return
        self.last_hitl_expiry = now
        try:
            from backend.app.browser_v2.hitl import HITLResolutionService

            expired = await HITLResolutionService(self.store, clock=self.clock).expire_stale(now)
            if expired:
                self.housekeeping_log.append({"hitl_expired": len(expired)})
        except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
            logger.warning("hitl expiry failed: %s", type(exc).__name__)

    async def decay_priorities(self, now: datetime) -> None:
        """Phase 9B: stale early-bird tiers decay (P0 -> P1 after 2 h, P1 -> P2 after 24 h) every 10 min."""
        if self.last_decay is not None and (now - self.last_decay).total_seconds() < DECAY_EVERY_SEC:
            return
        self.last_decay = now
        try:
            changed = await self.store.decay_priorities(now)
            if changed:
                self.housekeeping_log.append({"priority_decayed": changed})
        except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
            logger.warning("priority decay failed: %s", type(exc).__name__)

    async def send_digest(self, now: datetime, reader: Any = None) -> None:
        if self.digest is None or self.notify is None:
            return
        try:
            if not await self.digest.due(now):
                return
            claimed, previous = await self.digest.claim(now)
            if not claimed:
                return  # another process/restart already sent today's digest
            from backend.app.browser_v2.digest import build_digest

            try:
                text = await build_digest(self.store, now, ai=getattr(self.service, "ai", None),
                                          mail_events=getattr(reader, "events", None))
                await self.notify(text)
            except Exception:
                await self.digest.release(now, previous)  # retried on the next housekeeping tick
                raise
            await self.digest.mark_sent(now)
            self.housekeeping_log.append({"digest": now.isoformat()})
        except Exception as exc:  # noqa: BLE001
            logger.warning("digest failed: %s", type(exc).__name__)

    async def run_profile_sync(self) -> None:
        """Phase 9D: due portal profile syncs, between jobs only (the scheduler holds the single tab)."""
        scheduler = getattr(self, "profile_sync", None)
        if scheduler is None:
            return
        try:
            await scheduler.run_due()
        except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
            logger.warning("profile sync failed: %s", type(exc).__name__)
