"""Bounded Naukri alerts from the existing approved local Gmail account.

No new OAuth grant, mailbox writes, email-link requests or vacancy claims. A
durable date/page cursor and transactionally saved receipts make reads resumable.
START/PAUSE/STOP and account/policy generations fence every network operation
and the final publish. Candidate facts still use the existing review pipeline.
"""

import re
from datetime import timedelta
from email.utils import parseaddr
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import Field, StrictBool
from sqlalchemy import or_, select

from backend.app.ai.schemas import Contract
from backend.app.dashboard.models import Notification, OwnerPreference
from backend.app.execution import recurring, store
from backend.app.execution.naukri import normalized_url
from backend.app.integrations.gmail.mailboxes import Mailboxes, Slot, digest, headers
from backend.app.integrations.gmail.read_client import (
    IDENTIFIER,
    GmailReadClient,
    content_evidence,
)
from backend.app.integrations.token_store import ConnectionError
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.discovery import now
from backend.app.models.job import Job

PREFIX = "gm54_alerts:"
SENDER = "naukrialerts@naukri.com"


class AlertPolicy(Contract):
    expected_version: int = Field(ge=0)
    expected_generation: int = Field(ge=1)
    enabled: StrictBool
    interval_seconds: int = Field(900, ge=900, le=86400)


async def status(session, slot):
    row = await session.get(OwnerPreference, PREFIX + slot, populate_existing=True)
    value = row.value if row else {"version": 0, "enabled": False}
    account = await session.get(OwnerPreference, "gm54_account:" + slot, populate_existing=True)
    enabled = bool(value.get("enabled") and account and account.value.get("status") == "connected"
                   and account.value.get("generation") == value.get("generation"))
    return {k: v for k, v in value.items() if k not in {"lease", "lease_until", "page_token"}} | {
        "enabled": enabled, "configured_enabled": value.get("enabled", False),
        "sender": SENDER, "sending_enabled": False, "links_opened": False,
    }


async def configure(session, settings, slot: Slot, policy: AlertPolicy):
    mailbox = Mailboxes(session, settings)
    mailbox.enabled()
    if not settings.GMAIL_READ_BODY_REVIEWED:
        raise ConnectionError("gmail_body_access_review_required")
    await store.memory_row(session, lock=True)
    account = await mailbox.fence(slot, policy.expected_generation)
    row = await session.get(OwnerPreference, PREFIX + slot, populate_existing=True)
    value = dict(row.value) if row else {"version": 0}
    if value["version"] != policy.expected_version:
        raise ConnectionError("gmail_alert_policy_changed")
    same_account = value.get("generation") == policy.expected_generation
    value = {**(value if same_account else {}), "version": value["version"] + 1,
             "enabled": policy.enabled, "generation": policy.expected_generation,
             "account_email": account.value["account_email"],
             "interval_seconds": policy.interval_seconds, "next_check_at": None,
             "lease": None, "lease_until": None}
    await recurring.put(session, PREFIX + slot, value)
    await session.flush()
    return await status(session, slot)


def authenticated_alert(message):
    """Require Gmail's unambiguous receiving-domain DMARC result before body use."""
    raw = (message.get("payload") or {}).get("headers", [])
    if not isinstance(raw, list) or len(raw) > 100:
        return False
    if any(not isinstance(h, dict) or not isinstance(h.get("name"), str)
           or not isinstance(h.get("value"), str) for h in raw):
        return False
    from_headers = [h.get("value", "") for h in raw if h.get("name", "").casefold() == "from"]
    auth = [h.get("value", "") for h in raw if h.get("name", "").casefold() == "authentication-results"]
    if len(from_headers) != 1 or parseaddr(from_headers[0])[1].casefold() != SENDER or len(auth) != 1:
        return False
    result = " ".join(auth[0].casefold().split())
    return (result.startswith("mx.google.com;")
            and re.search(r"(?:^|[;\s])dmarc=pass\b[^;]*\bheader\.from=naukri\.com(?=[;\s]|$)", result) is not None
            and re.search(r"(?:^|[;\s])dkim=pass\b[^;]*\bheader\.(?:i=@|d=)naukri\.com(?=[;\s]|$)", result) is not None)


def query_for(value):
    return (f"in:inbox from:{SENDER} after:{value['scan_after']} "
            f"before:{value['scan_until']}")


async def retain(session, slot, account, message, received):
    """Publish candidates, not invented jobs. Existing/applied jobs stay intact."""
    from backend.app.integrations.gmail.alert_candidates import record_candidates

    evidence = content_evidence(message.get("payload", {}))
    candidates = await record_candidates(session, source="gmail", account=account["account_email"],
        message_id=message["id"], sender=SENDER, links=evidence["links"], monitoring_authorized=True)
    added = 0
    if not candidates:
        return 0, 0
    identities = {c["requisition"]: str(uuid5(NAMESPACE_URL, "gmail-naukri-alert:" + c["requisition"])) for c in candidates}
    jobs = list((await session.scalars(select(Job).where(Job.source_platform == "naukri", or_(
        *(Job.job_url.like("%-" + req + suffix) for req in identities for suffix in ("", "/"))
    )))).all())
    prior_urls = (await session.scalars(select(Job.job_url).join(ApplicationPacket, ApplicationPacket.job_id == Job.id).where(
        Job.source_platform == "naukri", ApplicationPacket.lifecycle_state.in_([
            "user_reported_submitted", "provider_confirmed_submitted", "submitting", "submission_unknown"])
    ))).all()
    applied_requisitions = {_requisition(url) for url in prior_urls}
    existing_candidates = {r.key: r for r in (await session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.in_(["nau_alert:" + identity for identity in identities.values()])
    ).execution_options(populate_existing=True))).all()}
    existing_notifications = set((await session.scalars(select(Notification.dedup_key).where(
        Notification.dedup_key.in_(["gmail-alert:" + identity for identity in identities.values()])
    ))).all())
    deliveries = []
    for candidate in candidates:
        requisition = candidate["requisition"]
        identity = identities[requisition]
        key = "nau_alert:" + identity
        row = existing_candidates.get(key)
        # Use requisition identity, including owner imports with another URL slug.
        existing = next((job for job in jobs if _requisition(job.job_url) == requisition), None)
        applied = requisition in applied_requisitions or any(
            _requisition(job.job_url) == requisition and (job.status in {"applied", "submitted"}
                or (job.discovery_metadata or {}).get("data_provenance", {}).get("posting_status") == "already_applied")
            for job in jobs)
        state = "ALREADY_APPLIED" if applied else "EXISTING_JOB" if existing else "NEEDS_INPUT"
        reference = "gmail:" + slot + ":" + message["id"]
        value = {"id": identity, "account_id": "local:" + slot, "requisition_id": requisition,
                 "url": candidate["url"], "state": state, "title": None, "employer": None,
                 "reason": "already_applied" if applied else "existing_saved_job" if existing
                 else "verified_vacancy_facts_required", "source": "gmail_job_alerts",
                 "message_references": [reference], "received_at": received,
                 "last_observation": now().isoformat(), "expires_at": (now() + timedelta(days=14)).isoformat(),
                 "posting_status": "unknown", "sender_authenticity": "gmail_reported_dmarc_and_dkim_pass",
                 "submitted": False, "job_id": str(existing.id) if existing else None}
        if row and row.value.get("state") != "EXPIRED":
            value = {**row.value, "last_observation": value["last_observation"],
                     "message_references": list(dict.fromkeys([*row.value["message_references"], reference]))[-10:]}
            if applied:
                value.update(state="ALREADY_APPLIED", reason="already_applied")
        else:
            added += 1
            notification_key = "gmail-alert:" + identity
            if state == "NEEDS_INPUT" and notification_key not in existing_notifications:
                session.add(Notification(dedup_key=notification_key, kind="job_match",
                    title="Naukri alert candidate requires vacancy facts",
                    body="Authenticated Naukri alert contains a direct requisition link. Employer facts and active vacancy remain unverified.",
                    href="/jobs"))
            from backend.app.core.config import get_settings
            from backend.app.local_agent.models import TelegramDelivery
            from backend.app.services.discovery_budget import insert_for

            settings = get_settings()
            if state == "NEEDS_INPUT" and settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_OWNER_CHAT_ID:
                delivery_id = -int(digest(notification_key)[:15], 16) - (1 << 60)
                deliveries.append({"update_id": delivery_id, "state": "pending",
                    "reply": "Naukri alert candidate " + requisition + ": saved for factual vacancy review. No fields filled or application sent. Open Jobs in Automated Apply."})
        if row:
            row.value = value
        else:
            session.add(OwnerPreference(key=key, value=value))
    if deliveries:
        await session.execute(insert_for(session)(TelegramDelivery).values(deliveries).on_conflict_do_nothing())
    await session.flush()
    return added, len(candidates)


def _requisition(url):
    try:
        return normalized_url(url).rsplit("-", 1)[-1]
    except (ValueError, TypeError):
        return None


async def poll(factory, settings, slot: Slot = "1", *, force=False, mailbox_factory=Mailboxes):
    """At most five selected alert messages per cycle; no arbitrary query input."""
    if not settings.GMAIL_LOCAL_ACCOUNTS_ENABLED or not settings.GMAIL_READ_BODY_REVIEWED:
        return {"status": "disabled_or_paused", "submitted": False}
    async with factory() as session:
        # Idle/disabled alert intake must not compete with browser commands for
        # the global owner lock on every five-second worker tick.
        row = await session.get(OwnerPreference, PREFIX + slot)
        if not row or not row.value.get("enabled"):
            return {"status": "disabled_or_paused", "submitted": False}
        if not force and row.value.get("next_check_at") and row.value["next_check_at"] > now().isoformat():
            return {"status": "not_due", "submitted": False}
        await store.memory_row(session, lock=True)
        automation = await recurring.record(session)
        row = await session.get(OwnerPreference, PREFIX + slot, populate_existing=True)
        if automation["state"] != "RUNNING" or not row or not row.value.get("enabled"):
            return {"status": "disabled_or_paused", "submitted": False}
        value = dict(row.value)
        if value.get("lease_until", "") and value["lease_until"] > now().isoformat():
            return {"status": "leased", "submitted": False}
        if not force and value.get("next_check_at", "") and value["next_check_at"] > now().isoformat():
            return {"status": "not_due", "submitted": False}
        if (await store.configuration(session)).mode == "OFF":
            return {"status": "disabled_or_paused", "submitted": False}
        lease, revision = str(uuid4()), automation["revision"]
        value.update(lease=lease, lease_until=(now() + timedelta(seconds=180)).isoformat(),
                     next_check_at=(now() + timedelta(seconds=value["interval_seconds"])).isoformat())
        if not value.get("page_token"):
            # Fixed upper bound avoids skipping arrivals during pagination. The
            # overlap plus durable message IDs catches late/reordered messages.
            value.update(scan_after=max(int((now() - timedelta(days=30)).timestamp()),
                                        int(value.get("watermark", 0)) - 86400),
                         scan_until=int(now().timestamp()) + 1)
        await recurring.put(session, PREFIX + slot, value)
        await session.commit()
    result = {"messages": 0, "listed_messages": 0, "already_processed": 0,
              "authenticated": 0, "candidates_added": 0, "direct_links": 0,
              "rejected_origin": 0, "rejected_topic": 0, "without_direct_links": 0,
              "submitted": False, "links_opened": False}
    async with factory() as session:
        mailbox = mailbox_factory(session, settings)

        async def guard():
            await store.memory_row(session, lock=True)
            current = await recurring.record(session)
            row = await session.get(OwnerPreference, PREFIX + slot, populate_existing=True)
            if (current["state"] != "RUNNING" or current["revision"] != revision or not row
                    or not row.value.get("enabled") or row.value["version"] != value["version"]
                    or row.value.get("lease") != lease or row.value["lease_until"] <= now().isoformat()
                    or (await store.configuration(session)).mode == "OFF"):
                raise ConnectionError("gmail_alert_authority_changed")
            await mailbox.fence(slot, value["generation"])

        try:
            await guard()
            await session.commit()
            token, account = await mailbox.access(slot)
            await guard()
            await session.commit()
            reader = GmailReadClient(token, mailbox.client)
            page = await reader.messages(labels=["INBOX"], query=query_for(value),
                                         page_token=value.get("page_token"), limit=5)
            messages = page.get("messages", [])
            if not isinstance(messages, list) or len(messages) > 5:
                raise ConnectionError("gmail_alert_page_invalid")
            result["listed_messages"] = len(messages)
            for item in messages:
                message_id = item.get("id") if isinstance(item, dict) else None
                if not isinstance(message_id, str) or not IDENTIFIER.fullmatch(message_id):
                    raise ConnectionError("gmail_message_id_invalid")
                await guard()
                key = "gm54_alertmsg:" + digest(account["google_subject"] + ":" + message_id)[:32]
                seen = await session.get(OwnerPreference, key)
                await session.commit()
                if seen:
                    result["already_processed"] += 1
                    continue
                # Metadata selection and authentication precede the body read.
                message = await reader.message(message_id)
                if message.get("id") != message_id or "INBOX" not in message.get("labelIds", []):
                    raise ConnectionError("gmail_message_selection_changed")
                result["messages"] += 1
                trusted = authenticated_alert(message)
                if trusted:
                    await guard()
                    await session.commit()
                    message = await reader.message(message_id, body=True)
                    if (message.get("id") != message_id or "INBOX" not in message.get("labelIds", [])
                            or not authenticated_alert(message)):
                        raise ConnectionError("gmail_message_selection_changed")
                    result["authenticated"] += 1
                else:
                    result["rejected_origin"] += 1
                await guard()
                if trusted:
                    # Only job alert topics, never arbitrary official newsletters.
                    if re.search(r"\b(?:jobs?|hiring|vacanc\w*|recommend\w*|opportunit\w*)\b", headers(message).get("subject", ""), re.I):
                        added, links = await retain(session, slot, account, message, now().isoformat())
                        result["candidates_added"] += added
                        result["direct_links"] += links
                        if not links:
                            result["without_direct_links"] += 1
                    else:
                        result["rejected_topic"] += 1
                await recurring.put(session, key, {"message_id": message_id,
                    "generation": value["generation"], "origin_accepted": trusted,
                    "processed_at": now().isoformat(), "body_stored": False})
                await session.commit()
            await guard()
            row = await session.get(OwnerPreference, PREFIX + slot, populate_existing=True)
            next_page = page.get("nextPageToken")
            if next_page is not None and (not isinstance(next_page, str) or len(next_page) > 2048):
                raise ConnectionError("gmail_alert_page_invalid")
            result["has_more_pages"] = bool(next_page)
            row.value = {**row.value, "page_token": next_page,
                         "watermark": value.get("watermark", 0) if next_page else value["scan_until"] - 1,
                         "last_result": result, "last_check_at": now().isoformat(),
                         "lease": None, "lease_until": None, "error": None}
            await session.commit()
            return {"status": "observed", **result}
        except Exception:
            await session.rollback()
            # Keep the cursor and any committed message receipts. A later safe
            # read resumes, while STOP/account changes fence publication now.
            try:
                row = await session.get(OwnerPreference, PREFIX + slot, with_for_update=True, populate_existing=True)
                # Cleanup only our lease, even after STOP/disconnect. This
                # publishes no candidates and cannot clear a successor lease.
                if row and row.value.get("lease") == lease and row.value["version"] == value["version"]:
                    row.value = {**row.value, "lease": None, "lease_until": None,
                                 "page_token": None, "error": "gmail_alert_cycle_failed",
                                 "last_check_at": now().isoformat()}
                    await session.commit()
            except Exception:
                await session.rollback()
            raise
