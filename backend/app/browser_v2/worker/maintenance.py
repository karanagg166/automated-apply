"""Worker mixin: Phase 6A/8 housekeeping (mail watchers, HITL expiry, nightly digest)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.reports import (
    DECAY_EVERY_SEC,
    HITL_EXPIRY_EVERY_SEC,
    STALE_APPLYING_AFTER_SEC,
    STALE_APPLYING_EVERY_SEC,
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
                # With the router, alerts go out via the bus topic below (P1 rollup, deduped) only.
                direct = None if getattr(self, "notifier", None) is not None else self.notify
                # Milestone 2: funnel first, so a mail matched to an application is recorded (and alerted)
                # once; the recruiter watcher below then skips the same message key.
                await self.reconcile_mail_funnel(reader)
                replies = await reader.scan_recruiter_replies(self.store, notify=direct)
                publish = getattr(self.service, "publish", None)
                for alert in replies.alerts:
                    if publish is not None:
                        await publish("mail.recruiter_reply", {"alert": alert[:200]})
                alerts = await reader.scan_job_alert_emails(self.store)
                self.housekeeping_log.append({"mail_scan": now.isoformat(), "replies": replies.new_events,
                                              "alert_jobs": alerts.discovered, "tier": replies.tier})
            except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
                logger.warning("mail watcher failed: %s", type(exc).__name__)
        await self.recover_stale_applying(now)
        await self.drain_outreach()
        await self.expire_hitl(now)
        await self.decay_priorities(now)
        await self.run_profile_sync()
        await self.send_digest(now, reader)
        del self.housekeeping_log[:-50]

    async def reconcile_mail_funnel(self, reader: Any) -> None:
        """Milestone 2: confirmation / OA / interview / rejection mails -> applications (read-only)."""
        try:
            from backend.app.browser_v2.worker.funnel_reconcile import FunnelReconciler

            report = await FunnelReconciler(self.store, reader, publish=getattr(self.service, "publish", None),
                                            clock=self.clock).run()
            if report.matched or report.needs_reconciliation:
                self.housekeeping_log.append({"funnel_matched": report.matched, "funnel_verified": report.verified,
                                              "funnel_upgraded": report.upgraded,
                                              "needs_reconciliation": report.needs_reconciliation})
        except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
            logger.warning("mail funnel reconcile failed: %s", type(exc).__name__)

    async def drain_outreach(self) -> None:
        """Milestone 2: opt-in high-score outreach DRAFTS queued by `job.applied` (never sends)."""
        handoff = getattr(self, "outreach", None)
        if handoff is None:
            return
        try:
            await handoff.drain()
        except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
            logger.warning("outreach draft handoff failed: %s", type(exc).__name__)

    async def recover_stale_applying(self, now: datetime) -> None:
        """A crash/kill between the APPLYING reservation and its outcome leaves a row that nothing
        schedules, reconciles or counts. Move it to SUBMISSION_UNKNOWN (never replayed; the existing
        reconcile pass can still confirm it APPLIED from portal history)."""
        last = self.last_stale_recovery
        if last is not None and (now - last).total_seconds() < STALE_APPLYING_EVERY_SEC:
            return
        self.last_stale_recovery = now
        try:
            from backend.app.browser_v2.state import ApplicationState

            stale = await self.store.stale_applying(now - timedelta(seconds=STALE_APPLYING_AFTER_SEC))
            recovered = 0
            for record in stale:
                try:
                    await self.store.transition(record, ApplicationState.SUBMISSION_UNKNOWN,
                                                "stale_applying_recovered")
                    recovered += 1
                except Exception as exc:  # noqa: BLE001 - a concurrent writer won; next sweep re-checks
                    logger.warning("stale APPLYING %s not recovered: %s", record.id, type(exc).__name__)
            if recovered:
                logger.warning("recovered %d stale APPLYING row(s) as SUBMISSION_UNKNOWN", recovered)
                self.housekeeping_log.append({"stale_applying_recovered": recovered})
        except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
            logger.warning("stale APPLYING recovery failed: %s", type(exc).__name__)

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
            from backend.app.browser_v2.digest import build_digest_report

            notifier = getattr(self, "notifier", None)
            try:
                queued = await notifier.pending_digest() if notifier is not None else []
                text, meaningful = await build_digest_report(
                    self.store, now, ai=getattr(self.service, "ai", None),
                    mail_events=getattr(reader, "events", None), queued=queued)
                if meaningful or not getattr(self.digest, "skip_empty", False):
                    await self.notify(text)
                if notifier is not None and queued:
                    await notifier.mark_digest_delivered(queued)
            except Exception:
                await self.digest.release(now, previous)  # retried on the next housekeeping tick
                raise
            await self.digest.mark_sent(now)
            self.housekeeping_log.append({"digest": now.isoformat(), "sent": meaningful})
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
