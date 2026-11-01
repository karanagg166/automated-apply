"""Bounded ordinary-UI execution and independent, read-only reconciliation.

No provider call runs inside these transactions. A browser Apply is a single
durably admitted action, never a receipt. Unknown actions can only be reconciled.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import Notification, OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.queue_contracts import QueuePolicy

READS = {"inspect_profile", "inspect_application", "reconcile_application", "verify_account"}
OPERATIONS = READS | {"apply"}
PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
HISTORY_URL = "https://www.naukri.com/myapply/historypage"
RECEIPT_PREFIX = "naukri_worker_receipt:"


def browser_url(value):
    return {"inspect_profile": PROFILE_URL, "verify_account": PROFILE_URL,
            "reconcile_application": HISTORY_URL}.get(value["operation"], value["url"])


def account_observation(value):
    proof = value.get("account_observation") or {}
    if (not value.get("binding") or proof.get("account_sha256") != value.get("account_sha256")
            or proof.get("binding") != value.get("binding")
            or proof.get("work_id") != value.get("id")
            or proof.get("source") != "profile_ui"):
        return None
    return proof


def account_current(value, now):
    proof = account_observation(value)
    try:
        at = datetime.fromisoformat(proof["observed_at"]) if proof else None
        return bool(at and at.tzinfo is not None
                    and re.fullmatch(r"[A-Za-z0-9_-]{16,100}", str(proof.get("profile_document_id", "")))
                    and timedelta(0) <= now - at <= timedelta(minutes=2))
    except (TypeError, ValueError, KeyError):
        return False


def retain_account_observation(value, observation, now):
    value["account_observation"] = {
        "source": "profile_ui", "work_id": value["id"],
        "account_sha256": observation.account_sha256,
        "profile_document_id": observation.document_id,
        "observed_at": now.isoformat(), "binding": dict(value["binding"]),
    }


def descriptor(value):
    return {
        "expected_account_sha256": value.get("account_sha256"),
        "expected_resume_sha256": value.get("upload_preflight", {}).get("sha256"),
        "account_observation": account_observation(value),
        "expected_title": value.get("title"), "expected_company": value.get("company"),
        "document_id": value.get("document_id"),
        "control_sha256": value.get("control_sha256"),
        "permit_expires_at": value.get("permit_expires_at"),
    }


async def recover_unknown(session):
    """Schedule only history reads. Reconciliation is bounded across restarts."""
    config = await queue.configuration(session)
    if config["state"] != "RUNNING":
        return
    await queue.store.memory_row(session, lock=True)
    now = await instant(session)
    candidates = select(OwnerPreference).where(
        OwnerPreference.key.startswith(queue.PREFIX),
        OwnerPreference.value["stage"].as_string().not_in(queue.TERMINAL),
        OwnerPreference.value["status"].as_string() == "unknown",
    ).execution_options(populate_existing=True)
    for row in (await session.scalars(candidates)).all():
        v = dict(row.value)
        if (v["status"] != "unknown" or v.get("reconciliation_attempts", 0) >= 3
                or v.get("account_recheck_attempts", 0) >= 3):
            continue
        if not v.get("account_sha256"):
            continue
        v.update(operation="reconcile_application", status="queued", stage="SUBMISSION_UNKNOWN",
                 revision=v["revision"] + 1, lease_token=None, lease_until=None,
                 available_at=(now + timedelta(seconds=60)).isoformat())
        row.value = v
        await queue.event(session, v, "read_only_reconciliation_scheduled")


async def receive(session, value, report, settings):
    op, observation = value["operation"], report.execution
    now = await instant(session)
    if report.kind in {"needs_input", "failed"}:
        # Lost responses and page errors after admission can never make Apply
        # resumable. Even a definite refusal is retained with its original action.
        uncertain = op == "apply" or bool(value.get("admitted_actions"))
        value.update(stage="SUBMISSION_UNKNOWN" if uncertain else "BLOCKED_PLATFORM",
                     status="unknown" if uncertain else "waiting",
                     reason=report.reason or "provider_execution_unconfirmed")
        return False
    if not observation or report.kind != "execution_observation":
        raise ToolDenied("execution_observation_required")
    if str(report.observed_url) != browser_url(value):
        raise ToolDenied("queue_document_identity_changed")
    if report.requisition != value["requisition"]:
        raise ToolDenied("queue_requisition_changed")
    if observation.account_sha256 != value.get("account_sha256"):
        raise ToolDenied("provider_account_identity_changed")
    if op == "verify_account":
        if observation.state != "PROFILE_OBSERVED":
            raise ToolDenied("provider_account_profile_observation_required")
        retain_account_observation(value, observation, now)
        # A history-account read can only continue reconciliation, never Apply.
        value.update(operation="reconcile_application", status="leased")
        return True
    if op == "inspect_profile":
        if observation.state != "PROFILE_VERIFIED":
            raise ToolDenied("provider_resume_observation_required")
        from backend.app.execution.naukri_upload import preflight
        from backend.app.services.applications.service import ApplicationPacketService

        packet = await ApplicationPacketService(session).read(UUID(value["packet_id"]))
        checked = await preflight(session, packet, settings)
        if (checked["state"] != "PDF_VERIFIED_LOCAL"
                or observation.resume_sha256 != checked["sha256"]
                or observation.resume_bytes != checked["byte_count"]):
            raise ToolDenied("provider_saved_resume_differs_from_canonical_pdf")
        value["facts"] = {**value["facts"], "provider_resume_source": "profile_download_ui",
                          "provider_resume_checked_at": now.isoformat(), "provider_resume_sha256": checked["sha256"]}
        retain_account_observation(value, observation, now)
        value.update(operation="inspect_application", status="leased", stage="READY_TO_APPLY")
        return True
    if op == "inspect_application":
        if not account_current(value, now):
            raise ToolDenied("fresh_provider_account_observation_required")
        if observation.title != value["title"] or observation.company != value["company"]:
            raise ToolDenied("provider_job_or_company_changed")
        if observation.state == "APPLIED":
            value.update(stage="VERIFYING", status="queued", operation="reconcile_application", reason="already_applied_reconcile_only")
            return False
        if observation.state != "NOT_APPLIED" or not observation.control_sha256 or not report.job:
            raise ToolDenied("supported_direct_apply_control_required")
        if report.job.requisition != value["requisition"] or report.job.title != value["title"] or report.job.company != value["company"]:
            raise ToolDenied("provider_job_or_company_changed")
        # Current observed facts, including exact timestamp/applicant bounds,
        # replace the old listing before the durable eligibility admission.
        prior_facts = value["facts"]
        observed_facts = report.job.model_dump(mode="json")
        material = set(observed_facts) - {"evidence_sha256", "applicants_min", "applicants_max"}
        if any(prior_facts.get(k) != observed_facts[k] for k in material):
            value.update(stage="NEEDS_INPUT", status="waiting", reason="listing_changed_refresh_packet_required")
            return False
        value["facts"] = {**prior_facts, **observed_facts,
                          "prior_status": "NOT_APPLIED", "prior_status_checked_at": now.isoformat()}
        from backend.app.models.job import Job

        # Same material listing: retain its packet context and provenance. Fresh
        # applicant bounds still participate in admission without inventing facts.
        job = await session.get(Job, UUID(value["job_id"]), populate_existing=True)
        policy = QueuePolicy.model_validate((await queue.configuration(session))["policy"])
        await queue.eligible_context(session, value, policy, job)
        value.update(operation="apply", status="leased", stage="READY_TO_APPLY",
                     document_id=observation.document_id, control_sha256=observation.control_sha256)
        return True
    if op == "apply":
        if observation.document_id != value.get("document_id"):
            raise ToolDenied("queue_document_identity_changed")
        if observation.state not in {"CLICKED", "QUESTIONNAIRE"}:
            raise ToolDenied("apply_action_observation_required")
        # Retain this exact attempt for its scoped questionnaire adapter.
        # This is neither a receipt nor authority to click Apply again.
        if observation.state == "QUESTIONNAIRE":
            value.update(stage="QUESTIONS", status="queued", operation="inspect_questionnaire", reason=None,
                         form_pending=True, form_binding=dict(value["binding"]))
        else:
            value.update(stage="VERIFYING", status="queued", operation="reconcile_application", reason="provider_confirmation_pending")
        return False
    if op != "reconcile_application" or observation.state != "APPLICATION_SENT":
        raise ToolDenied("persistent_provider_application_status_required")
    if not account_current(value, now):
        raise ToolDenied("fresh_provider_account_observation_required")
    if observation.title != value["title"] or observation.company != value["company"]:
        raise ToolDenied("provider_receipt_identity_changed")
    first = value.get("confirmation_observation")
    if not first:
        value["confirmation_observation"] = {"document_id": observation.document_id,
                                             "evidence_sha256": observation.evidence_sha256,
                                             "observed_at": now.isoformat()}
        value.update(stage="VERIFYING", status="queued", reason="provider_history_reload_required")
        return False
    if first["document_id"] == observation.document_id or datetime.fromisoformat(first["observed_at"]) >= now:
        raise ToolDenied("independent_history_reload_required")
    await confirm(session, value, observation, now, settings)
    return False


async def confirm(session, value, observation, now, settings):
    """One transaction: genuine evidence, canonical status, audit and notification."""
    value["form_pending"] = False
    from sqlalchemy import select

    from backend.app.models.application_packet import (
        ApplicationEvent,
        ApplicationPacket,
        ApplicationSubmissionEvidence,
    )
    from backend.app.models.job import Job

    key = RECEIPT_PREFIX + value["requisition"]
    existing = await session.get(OwnerPreference, key, populate_existing=True)
    if existing:
        raise ToolDenied("existing_worker_receipt_requires_review")
    receipt = {"requisition": value["requisition"], "queue_id": value["id"],
               "account_sha256": value["account_sha256"], "status": "Application Sent",
               "account_observation": account_observation(value),
               "confirmation_source": "naukri_application_status_ui", "operation_mode": "recurring_worker_ui",
               "observed_at": now.isoformat(), "persistent_after_reload": True,
               "first_observation": value["confirmation_observation"],
               "second_observation": observation.model_dump(mode="json"),
               "worker_dispatched": bool(value.get("admitted_actions"))}
    await queue.put(session, key, receipt)
    job = await session.get(Job, UUID(value["job_id"]), populate_existing=True)
    if job:
        job.status = "applied"
        job.discovery_metadata = {**(job.discovery_metadata or {}), "already_applied": True}
    packet = await session.get(ApplicationPacket, UUID(value["packet_id"]), populate_existing=True)
    previous_evidence = await session.scalar(select(ApplicationSubmissionEvidence.id).where(
        ApplicationSubmissionEvidence.packet_id == packet.id
    )) if packet else None
    if packet and not previous_evidence:
        prior = packet.lifecycle_state
        evidence = ApplicationSubmissionEvidence(
            id=uuid4(), packet_id=packet.id, packet_revision=packet.revision + 1,
            confirmation_source="naukri_status_ui", receipt_reference=key,
            evidence_confidence="provider_ui_persistent", human_confirmed=False,
            idempotency_key="naukri-worker-" + value["id"],
            request_hash=hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest(),
        )
        session.add(evidence)
        await session.flush()
        packet.revision += 1
        packet.approved_revision = None
        packet.lifecycle_state, packet.tracking_state, packet.readiness_state = "provider_confirmed_submitted", "applied_verified", "completed_verified"
        session.add(ApplicationEvent(packet_id=packet.id, packet_revision=packet.revision,
                                     event_type="naukri_persistent_ui_confirmed", previous_state=prior,
                                     next_state=packet.lifecycle_state, evidence_id=evidence.id,
                                     origin="local_worker"))
    value.update(stage="SUBMITTED_CONFIRMED", status="complete", operation=None,
                 reason=None, receipt_source="naukri_application_status_ui",
                 submission_mode="recurring_worker_ui" if receipt["worker_dispatched"] else "reconciled_provider_history")
    policy = QueuePolicy.model_validate((await queue.configuration(session))["policy"])
    if policy.notify_submitted:
        from backend.app.dashboard.notifications import preferences

        prefs = await preferences(session)
        title = "Naukri application confirmed"
        body = f"{value['title']} at {value['company']}: Application Sent persisted after a separate history reload."
        if not prefs.paused and prefs.in_app:
            session.add(Notification(dedup_key="naukri-confirmed:" + value["id"],
                                     kind="application_submitted", title=title, body=body,
                                     href="/applications/" + value["packet_id"]))
        if (policy.platforms["naukri"].notify_telegram and settings.TELEGRAM_BOT_TOKEN
                and settings.TELEGRAM_OWNER_CHAT_ID and settings.TELEGRAM_OWNER_USER_ID):
            from backend.app.local_agent.models import TelegramDelivery
            from backend.app.services.discovery_budget import insert_for

            delivery_id = -int(hashlib.sha256(("naukri-confirmed:" + value["id"]).encode()).hexdigest()[:15], 16) - (1 << 61)
            await session.execute(insert_for(session)(TelegramDelivery).values(
                update_id=delivery_id, state="pending", reply=title + ": " + body,
            ).on_conflict_do_nothing(index_elements=[TelegramDelivery.update_id]))
    await queue.event(session, value, "provider_submission_confirmed")
