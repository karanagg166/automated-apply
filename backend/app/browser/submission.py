"""Transactional submission authority, append-only history, fencing and recovery.

One stable record per packet prevents a new command/plan from resetting an attempt.
The default capability is off and every executable contract is localhost-test-only.
"""

import hashlib
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from backend.app.agent import store
from backend.app.agent.tools import ToolDenied, owner_allowed
from backend.app.automation.store import instant
from backend.app.browser.service import FormService, pdf_bytes
from backend.app.browser.submission_adapters import fixture_contract, verify_response
from backend.app.browser.submission_contracts import Submission, SubmissionApproval
from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.models import AgentOperation, TelegramDelivery
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.services.applications.resume_selector import digest
from backend.app.services.discovery_budget import insert_for

TRANSITIONS = {
    "prepared": {"form_inspected"},
    "form_inspected": {"form_filled"},
    "form_filled": {"awaiting_submission_approval"},
    "awaiting_submission_approval": {"submitting", "manual_required", "failed"},
    "submitting": {"submitted", "submission_uncertain", "manual_required", "failed"},
    "submission_uncertain": {"submitted", "manual_required"},
    "submitted": set(),
    "manual_required": set(),
    "failed": set(),
}


def key(application_id):
    return "submission:" + str(application_id)


def review_hash(s):
    fields = (
        "owner",
        "application_id",
        "job_id",
        "employer_id",
        "employer",
        "job_title",
        "plan_id",
        "campaign_id",
        "campaign_revision",
        "candidate_profile_id",
        "candidate_version",
        "context_digest",
        "packet_revision",
        "project_digest",
        "pdf_digest",
        "document_id",
        "document_digest",
        "adapter",
        "origin",
        "application_url",
        "request_url",
        "confirmation_url",
        "receipt_url",
        "nonce",
        "idempotency_key",
        "expires_at",
    )
    data = s.model_dump(mode="json")
    return digest({f: data[f] for f in fields})


def status_text(s):
    labels = {
        "prepared": "Prepared",
        "form_inspected": "Form inspected",
        "form_filled": "Form filled",
        "awaiting_submission_approval": "Awaiting approval",
        "submitting": "Submission in progress",
        "submitted": "Submitted with evidence",
        "submission_uncertain": "Submission uncertain; do not resubmit",
        "manual_required": "Manual action required",
        "failed": "Failed",
    }
    text = f"{s.employer} — {s.job_title}: {labels[s.state]}. Application {s.application_id}."
    if s.evidence:
        text += f" Receipt {s.evidence.application_id}; {s.evidence.type}; {s.evidence.destination}."
    if s.cancelled:
        text += " Remaining submissions stopped; any dispatched attempt still requires verification."
    return text


class SubmissionService:
    def __init__(self, session, settings):
        self.session, self.settings = session, settings

    def enabled(self, s=None):
        if (
            not self.settings.BROWSER_SUBMIT_ENABLED
            or not self.settings.BROWSER_AUTOMATION_ENABLED
        ):
            raise ToolDenied("submit_application_disabled")
        if s:
            self.validate_contract(s)
        elif (
            self.settings.ENVIRONMENT != "testing"
            or not self.settings.BROWSER_FIXTURE_ORIGIN
        ):
            raise ToolDenied("fixture_submission_only")

    def validate_contract(self, s):
        expected = fixture_contract(s.application_url, self.settings, s.idempotency_key)
        if any(
            getattr(s, k) != v for k, v in expected.items()
        ) or s.review_digest != review_hash(s):
            raise ToolDenied("submission_contract_changed")

    async def load(self, application_id, lock=True):
        await self.session.flush()
        row = await self.session.get(
            OwnerPreference,
            key(application_id),
            with_for_update=lock,
            populate_existing=True,
        )
        if not row:
            raise ToolDenied("submission_review_not_available")
        return row, Submission.model_validate(row.value)

    def save(self, row, s):
        row.value = s.model_dump(mode="json")

    async def audit(self, s, event, previous=None):
        s.revision += 1
        now = await instant(self.session)
        self.session.add(
            AgentOperation(
                key=f"submission:{s.id}:{s.revision}",
                actor=(s.authorization or {}).get("actor", "owner:primary"),
                command="submission:" + event,
                payload_hash=digest([str(s.id), s.revision, event, s.review_digest]),
                result={
                    "application_id": str(s.application_id),
                    "status": s.state,
                    "previous_state": previous,
                    "event": event,
                    "at": now.isoformat(),
                    "correlation_id": str(s.idempotency_key),
                    "evidence": s.evidence.model_dump(mode="json")
                    if s.evidence
                    else None,
                },
            )
        )

    async def transition(self, s, state, reason):
        if state not in TRANSITIONS[s.state]:
            raise ToolDenied("invalid_submission_transition")
        previous, s.state, s.reason = s.state, state, reason
        await self.audit(s, reason, previous)

    async def create_review(self, plan_id, campaign_id, snapshot):
        await store.memory_row(self.session, lock=True)
        forms = FormService(self.session, self.settings)
        _, plan = await forms.load(plan_id)
        prior = await self.session.get(
            OwnerPreference, key(plan.application_id), populate_existing=True
        )
        if prior:
            return Submission.model_validate(prior.value)
        packet = await forms.fresh(plan)
        _, campaign = await store.load(self.session, campaign_id, lock=True)
        job = await self.session.get(Job, plan.job_id, populate_existing=True)
        company = (
            await self.session.get(Company, job.company_id, populate_existing=True)
            if job.company_id
            else None
        )
        raw = await pdf_bytes(self.session, packet, self.settings)
        if (
            plan.mode != "local_automation"
            or plan.state != "finished"
            or campaign.state == "cancelled"
            or not company
            or not company.name
            or not raw
            or job.source_platform == "linkedin"
            or not plan.inspection.has_submit
            or plan.inspection.has_next
            or any(
                f.required and (a.needs_input or a.field_id not in plan.approved_fields)
                for f, a in zip(plan.inspection.fields, plan.actions)
            )
            or any(
                a.requires_review
                and not a.needs_input
                and a.field_id not in plan.approved_fields
                for a in plan.actions
            )
            or snapshot.get("state") != "reviewable"
            or snapshot.get("document_id") != plan.inspection.document_id
        ):
            raise ToolDenied(
                "complete_reviewed_form_company_and_canonical_pdf_required"
            )
        now = await instant(self.session)
        s = Submission(
            application_id=plan.application_id,
            job_id=plan.job_id,
            employer_id=company.id,
            employer=company.name,
            job_title=job.title,
            plan_id=plan.id,
            campaign_id=campaign.id,
            campaign_revision=campaign.revision,
            candidate_profile_id=packet.candidate_profile_id,
            candidate_version=packet.candidate_profile_version,
            context_digest=plan.context_digest,
            packet_revision=plan.packet_revision,
            project_digest=plan.project_digest,
            pdf_digest=hashlib.sha256(raw).hexdigest(),
            document_id=plan.inspection.document_id,
            document_digest=snapshot["document_digest"],
            expires_at=min(
                datetime.fromisoformat(plan.expires_at), now + timedelta(minutes=5)
            ).isoformat(),
            **fixture_contract(plan.target_url, self.settings, "pending"),
        )
        for k, v in fixture_contract(
            plan.target_url, self.settings, s.idempotency_key
        ).items():
            setattr(s, k, v)
        s.review_digest = review_hash(s)
        await self.audit(s, "prepared")
        for state in ("form_inspected", "form_filled", "awaiting_submission_approval"):
            await self.transition(s, state, state)
        self.session.add(
            OwnerPreference(key=key(s.application_id), value=s.model_dump(mode="json"))
        )
        await self.session.flush()
        return s

    async def fresh(self, s):
        self.enabled(s)
        if s.review_digest != review_hash(s):
            raise ToolDenied("submission_review_changed")
        _, campaign = await store.load(self.session, s.campaign_id, lock=True)
        forms = FormService(self.session, self.settings)
        _, plan = await forms.load(s.plan_id)
        packet = await forms.fresh(plan)
        job = await self.session.get(Job, s.job_id, populate_existing=True)
        company = await self.session.get(Company, s.employer_id, populate_existing=True)
        raw = await pdf_bytes(self.session, packet, self.settings)
        if (
            datetime.fromisoformat(s.expires_at) <= await instant(self.session)
            or campaign.revision != s.campaign_revision
            or campaign.state == "cancelled"
            or s.cancelled
            or not company
            or job.company_id != company.id
            or company.name != s.employer
            or job.title != s.job_title
            or job.source_platform == "linkedin"
            or s.job_id not in campaign.plan.selected_jobs
            or plan.state != "finished"
            or plan.inspection.document_id != s.document_id
            or packet.candidate_profile_id != s.candidate_profile_id
            or packet.candidate_profile_version != s.candidate_version
            or plan.context_digest != s.context_digest
            or plan.packet_revision != s.packet_revision
            or plan.project_digest != s.project_digest
            or plan.target_url != s.application_url
            or not raw
            or hashlib.sha256(raw).hexdigest() != s.pdf_digest
        ):
            raise ToolDenied("submission_scope_or_context_stale")
        return plan

    async def approve(self, application_id, actor, data: SubmissionApproval):
        if not owner_allowed(actor, self.settings):
            raise ToolDenied("authenticated_owner_required")
        await store.memory_row(self.session, lock=True)
        row, s = await self.load(application_id)
        await self.fresh(s)
        if (
            s.state != "awaiting_submission_approval"
            or s.dispatch_started_at
            or data.nonce != s.nonce
            or data.review_digest != s.review_digest
            or data.campaign_revision != s.campaign_revision
            or data.application_ids != [s.application_id]
        ):
            raise ToolDenied("exact_submission_scope_required")
        if not s.authorization:
            s.authorization = {
                **data.model_dump(mode="json"),
                "actor": f"{actor.channel}:{actor.identity}",
                "owner": "primary",
                "issued_at": (await instant(self.session)).isoformat(),
                "idempotency_key": str(s.idempotency_key),
            }
            await self.audit(s, "owner_authorized_exact_submission")
        self.save(row, s)
        return s

    def authorized(self, s):
        a = s.authorization or {}
        if (
            a.get("owner") != s.owner
            or a.get("scope") != "submit_application"
            or a.get("maximum_count") != 1
            or a.get("application_ids") != [str(s.application_id)]
            or a.get("nonce") != str(s.nonce)
            or a.get("review_digest") != s.review_digest
            or a.get("campaign_revision") != s.campaign_revision
            or a.get("idempotency_key") != str(s.idempotency_key)
            or not a.get("actor")
        ):
            raise ToolDenied("backend_submission_authorization_required")

    async def release(self, application_id, actor, command_campaign_id=None):
        if not owner_allowed(actor, self.settings):
            raise ToolDenied("authenticated_owner_required")
        await store.memory_row(self.session, lock=True)
        row, s = await self.load(application_id)
        if s.state != "awaiting_submission_approval":
            return s  # Never reset a dispatched or terminal attempt.
        await self.fresh(s)
        self.authorized(s)
        if command_campaign_id and command_campaign_id not in s.command_campaign_ids:
            s.command_campaign_ids.append(command_campaign_id)
        if not s.released:
            s.released = True
            await self.audit(s, "authorized_submission_queued")
        self.save(row, s)
        return s

    async def rows(self):
        await self.session.flush()
        return (
            await self.session.scalars(
                select(OwnerPreference)
                .where(OwnerPreference.key.like("submission:%"))
                .order_by(OwnerPreference.created_at.desc(), OwnerPreference.key)
            )
        ).all()

    async def claim(self):
        await store.memory_row(self.session, lock=True)
        now = await instant(self.session)
        filling = (
            await self.session.scalars(
                select(OwnerPreference.value).where(
                    OwnerPreference.key.like("browser_job:%"),
                    OwnerPreference.value["state"].as_string() == "running",
                )
            )
        ).all()
        if any(
            v.get("lease_until") and datetime.fromisoformat(v["lease_until"]) > now
            for v in filling
        ):
            return None
        # A plain MVCC read also sees active rows locked by a different transaction.
        active = await self.rows()
        if any(
            r.value["state"] == "submitting"
            and datetime.fromisoformat(r.value["lease_until"]) > now
            for r in active
        ):
            return None
        rows = (
            await self.session.scalars(
                select(OwnerPreference)
                .where(OwnerPreference.key.like("submission:%"))
                .order_by(OwnerPreference.created_at, OwnerPreference.key)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        for row in rows:
            s = Submission.model_validate(row.value)
            if s.state == "submitting":
                s.fence += 1
                s.lease_until = None
                await self.transition(
                    s, "submission_uncertain", "expired_lease_never_replay"
                )
                self.save(row, s)
                await self.publish(s)
            if s.state != "awaiting_submission_approval" or not s.released:
                continue
            try:
                await self.fresh(s)
                self.authorized(s)
            except ToolDenied:
                await self.transition(
                    s, "manual_required", "submission_revalidation_failed"
                )
                self.save(row, s)
                await self.publish(s)
                continue
            s.fence += 1
            s.lease_until = (now + timedelta(seconds=45)).isoformat()
            s.dispatch_started_at = now.isoformat()
            await self.transition(s, "submitting", "dispatch_intent_committed_no_retry")
            self.save(row, s)
            return s
        return None

    async def fenced(self, application_id, fence):
        row, s = await self.load(application_id)
        if (
            s.state != "submitting"
            or s.fence != fence
            or s.cancelled
            or datetime.fromisoformat(s.lease_until) <= await instant(self.session)
        ):
            raise ToolDenied("submission_lease_lost")
        return row, s

    async def complete(
        self, application_id, fence, response=None, *, preflight_failed=False
    ):
        row, s = await self.load(application_id)
        if s.state in {
            "submitted",
            "submission_uncertain",
            "manual_required",
            "failed",
        }:
            return s
        if (
            s.state != "submitting"
            or s.fence != fence
            or s.cancelled
            or datetime.fromisoformat(s.lease_until) <= await instant(self.session)
        ):
            raise ToolDenied("submission_lease_lost")
        state, evidence = (
            ("manual_required", None)
            if preflight_failed
            else verify_response(s, response, await instant(self.session))
        )
        s.evidence, s.lease_until = evidence, None
        reason = (
            "pre_dispatch_revalidation_failed"
            if preflight_failed
            else "verified_submission_receipt"
            if state == "submitted"
            else "confirmation_ambiguous_no_retry"
        )
        if state == "failed":
            import json

            reason = (
                "employer_validation_failed"
                if json.loads(response["body"]).get("status") == "validation_failed"
                else "employer_rejected"
            )
        await self.transition(s, state, reason)
        await self.persist_evidence(s)
        self.save(row, s)
        await self.publish(s)
        return s

    async def persist_evidence(self, s):
        if s.state != "submitted" or not s.evidence:
            return
        # Existing packet tables intentionally forbid provider-confirmed submissions.
        # Fixture acceptance uses the private append-only receipt ledger, without
        # relaxing those live rollout guards or mislabelling fixture evidence as live.
        receipt_key = f"submission_receipt:{s.idempotency_key}"
        previous = await self.session.get(AgentOperation, receipt_key)
        if previous:
            raise ToolDenied("existing_submission_evidence_conflict")
        self.session.add(
            AgentOperation(
                key=receipt_key,
                actor=s.authorization["actor"],
                command="submission_receipt_verified",
                payload_hash=s.review_digest,
                result={
                    "status": "submitted",
                    "scope": "localhost_fixture",
                    "application_id": str(s.application_id),
                    "evidence": s.evidence.model_dump(mode="json"),
                },
            )
        )
        job = await self.session.get(Job, s.job_id, with_for_update=True)
        job.status = "applied"

    async def reconcile(self, application_id, response):
        await store.memory_row(self.session, lock=True)
        row, s = await self.load(application_id)
        if s.state != "submission_uncertain":
            return s
        self.validate_contract(s)
        state, evidence = verify_response(
            s, response, await instant(self.session), reconciliation=True
        )
        if state == "submitted":
            s.evidence = evidence
            await self.transition(s, "submitted", "read_only_receipt_reconciled")
            await self.persist_evidence(s)
        else:
            s.reason = "receipt_not_authoritative_manual_verification_required_no_retry"
            await self.audit(s, "read_only_reconciliation_inconclusive")
        self.save(row, s)
        await self.publish(s)
        return s

    async def stop_all(self):
        await store.memory_row(self.session, lock=True)
        for old in await self.rows():
            row, s = await self.load(UUID(old.value["application_id"]))
            if s.state not in {"awaiting_submission_approval", "submitting"}:
                continue
            s.cancelled, s.fence, s.lease_until = True, s.fence + 1, None
            await self.transition(
                s,
                "submission_uncertain" if s.dispatch_started_at else "manual_required",
                "owner_stopped_remaining_submissions",
            )
            self.save(row, s)
            await self.publish(s)

    async def publish(self, s):
        """Status text comes only from this durable result; versioned outbox dedupes replays."""
        for cid in {s.campaign_id, *s.command_campaign_ids}:
            row, campaign = await store.load(self.session, cid, lock=True)
            campaign.results = [
                r
                for r in campaign.results
                if not (
                    r.get("tool") == "submit_application"
                    and r.get("application_id") == str(s.application_id)
                )
            ]
            campaign.results.append(
                {
                    "tool": "submit_application",
                    "application_id": str(s.application_id),
                    "status": s.state,
                    "evidence": s.evidence.model_dump(mode="json")
                    if s.evidence
                    else None,
                }
            )
            campaign.reply = status_text(s)
            if campaign.state == "waiting_browser":
                store.transition(
                    campaign,
                    "completed" if s.state == "submitted" else "partially_completed",
                    await instant(self.session),
                    "persisted_submission_outcome",
                )
            store.save(row, campaign)
            if campaign.telegram_update_id is not None:
                # Stable per submission outcome across source/command campaigns and replays.
                outcome = digest(
                    [
                        str(s.id),
                        s.state,
                        s.cancelled,
                        s.evidence.model_dump(mode="json") if s.evidence else None,
                    ]
                )
                delivery_id = -int(outcome[:15], 16) - 1
                await self.session.execute(
                    insert_for(self.session)(TelegramDelivery)
                    .values(
                        update_id=delivery_id, reply=campaign.reply, state="pending"
                    )
                    .on_conflict_do_nothing()
                )
