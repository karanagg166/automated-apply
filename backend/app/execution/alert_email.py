"""Opt-in scheduled Gmail alert reads. Never follows email links or visits Naukri.

Reuse the existing GET-only, bounded, leased Gmail reader and its account-level
consent. Sender selection is not sender-authenticity proof. Messages expose
candidate requisition links only; missing employer/criteria/currentness remain
NEEDS_INPUT. No inference from a URL slug, and no raw body retention.
"""

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import recurring
from backend.app.execution.contracts import AutomationPolicy
from backend.app.execution.naukri import normalized_url
from backend.app.integrations.gmail.read_service import GmailReadService
from backend.app.integrations.token_store import ConnectionError

PREFIX = "nau_alert:"
# Owner scope decision: Gmail intake, two accounts and multi-account dedupe are
# Phase 5.4. Deployment flags cannot activate this dormant adapter in Phase 5.3.
PHASE54_GMAIL_INTAKE_READY = False


async def source_ready(session, policy, settings):
    if not PHASE54_GMAIL_INTAKE_READY:
        raise ToolDenied("gmail_intake_deferred_to_phase54")
    if not settings.NAUKRI_ALERT_EMAILS_ENABLED:
        raise ToolDenied("naukri_alert_email_activation_required")
    if not settings.GMAIL_READ_SYNC_ENABLED or not settings.GMAIL_READ_BODY_REVIEWED:
        raise ToolDenied("separate_gmail_read_and_body_approval_required")
    service = GmailReadService(session, settings)
    account = await service.account(policy.gmail_account_id)
    row = await service.policy_row(policy.gmail_account_id)
    selection = row.value.get("policy", {}) if row else {}
    senders = selection.get("sender_allowlist", [])
    if (
        account.status != "connected"
        or not account.google_subject
        or not account.last_verified_at
    ):
        raise ToolDenied("approved_gmail_account_not_connected")
    if not row or row.value["version"] != policy.gmail_policy_version:
        raise ToolDenied("gmail_alert_policy_changed")
    if (
        not selection.get("enabled")
        or not selection.get("read_body")
        or not senders
        or any(not str(sender).casefold().endswith("@naukri.com") for sender in senders)
        or selection.get("max_pages") != 1
        or selection.get("folders")
        or selection.get("history_months")
    ):
        raise ToolDenied("bounded_naukri_sender_body_policy_required")
    return service


def candidates(evidence, account_id, now):
    """Extract exact identities, retaining uncertainty instead of invented facts."""
    if (
        evidence.get("account_id") != str(account_id)
        or not evidence.get("expires_at")
        or evidence["expires_at"] <= now.isoformat()
    ):
        return []
    result = {}
    for link in evidence.get("links", [])[:25]:
        try:
            url = normalized_url(link)
        except (ValueError, TypeError):
            continue
        requisition = url.rsplit("-", 1)[-1]
        identity = str(uuid5(NAMESPACE_URL, f"naukri-alert:{account_id}:{requisition}"))
        result[identity] = {
            "id": identity,
            "account_id": str(account_id),
            "requisition_id": requisition,
            "url": url,
            "state": "NEEDS_INPUT",
            "title": None,
            "employer": None,
            "reason": "review_alert_authenticity_and_exact_job_facts",
            "source": "gmail_job_alerts",
            "message_references": [evidence["id"]],
            "received_at": evidence["received_at"],
            "last_observation": evidence["observed_at"],
            "expires_at": evidence["expires_at"],
            "posting_status": "unknown",
            "sender_authenticity": "unverified",
            "submitted": False,
        }
    return list(result.values())


async def retain_candidates(session, policy):
    now = await instant(session)
    # Only the selected account; no default/all-account scan or body reads here.
    rows = (
        await session.scalars(
            select(OwnerPreference)
            .where(
                OwnerPreference.key.startswith("gmail_msg:"),
                OwnerPreference.value["account_id"].as_string()
                == str(policy.gmail_account_id),
                OwnerPreference.value["selection_version"].as_integer()
                == policy.gmail_policy_version,
                OwnerPreference.value["body_selected"].as_boolean().is_(True),
            )
            .order_by(OwnerPreference.created_at.desc())
            .limit(100)
        )
    ).all()
    found = 0
    for row in rows:
        for candidate in candidates(row.value, policy.gmail_account_id, now):
            existing = await session.get(OwnerPreference, PREFIX + candidate["id"])
            if existing and existing.value.get("state") != "EXPIRED":
                # Preserve review state and all correlations across searches/retries.
                refs = list(
                    dict.fromkeys(
                        [
                            *existing.value["message_references"],
                            *candidate["message_references"],
                        ]
                    )
                )[-10:]
                existing.value = {**existing.value, "message_references": refs}
            else:
                await recurring.put(session, PREFIX + candidate["id"], candidate)
                found += 1
    return found


async def poll(factory):
    settings = get_settings()
    async with factory() as session, session.begin():
        await recurring.store.memory_row(session, lock=True)
        value = await recurring.record(session)
        if (
            value["state"] != "RUNNING"
            or not value["policy"]
            or value["policy"]["source"] != "gmail_job_alerts"
        ):
            return
        now = await instant(session)
        if (
            value.get("source_next_at")
            and datetime.fromisoformat(value["source_next_at"]) > now
        ):
            return
        if (
            value.get("source_lease_until")
            and datetime.fromisoformat(value["source_lease_until"]) > now
        ):
            return
        policy = AutomationPolicy.model_validate(value["policy"])
        try:
            await source_ready(session, policy, settings)
        except (ToolDenied, ConnectionError) as exc:
            value.update(
                source_error=str(exc),
                source_next_at=(
                    now + timedelta(seconds=policy.interval_seconds)
                ).isoformat(),
            )
            await recurring.put(session, recurring.KEY, value)
            return
        lease, revision = str(uuid4()), value["revision"]
        value.update(
            source_lease=lease,
            source_lease_until=(now + timedelta(seconds=180)).isoformat(),
            source_next_at=(
                now + timedelta(seconds=policy.interval_seconds)
            ).isoformat(),
        )
        await recurring.put(session, recurring.KEY, value)
    error = None
    async with factory() as session:

        async def guard():
            await recurring.store.memory_row(session, lock=True)
            current = await recurring.record(session)
            valid = (
                current["state"] == "RUNNING"
                and current["revision"] == revision
                and current.get("source_lease") == lease
                and datetime.fromisoformat(current["source_lease_until"])
                > await instant(session)
            )
            if valid:
                await source_ready(session, policy, settings)
                await recurring.put(
                    session,
                    recurring.HEALTH,
                    {"heartbeat_at": (await instant(session)).isoformat()},
                )
            await session.commit()  # Never hold a DB lock/pool slot over HTTP.
            if not valid:
                raise ConnectionError("naukri_alert_read_authority_lost")

        try:
            service = GmailReadService(session, settings)
            await service.sync(policy.gmail_account_id, authorization_guard=guard)
        except (ToolDenied, ConnectionError):
            await session.rollback()
            error = "gmail_alert_read_failed_or_authority_changed"
    async with factory() as session, session.begin():
        await recurring.store.memory_row(session, lock=True)
        current = await recurring.record(session)
        if (
            current["state"] != "RUNNING"
            or current["revision"] != revision
            or current.get("source_lease") != lease
        ):
            return  # A late read never publishes jobs after Stop/policy change.
        if error is None:
            await retain_candidates(session, policy)
        current.update(
            source_error=error,
            source_last_check_at=(await instant(session)).isoformat(),
            source_lease=None,
            source_lease_until=None,
        )
        await recurring.put(session, recurring.KEY, current)
