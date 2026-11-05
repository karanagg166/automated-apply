"""Continuation of one admitted Naukri attempt; never a second Apply.

The canonical packet stays ``submitting`` to fence every legacy/manual channel.
Questions/answers belong to its immutable revision and the retained browser step.
Model work runs outside the owner transaction and grants no browser action.
"""

import base64
import hashlib
import json
import re
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import store
from backend.app.execution.queue_contracts import QueuePolicy

READS = {
    "inspect_questionnaire",
    "refresh_questionnaire_profile",
    "refresh_questionnaire_job",
}
WRITES = {"answer_questionnaire"}
OPERATIONS = READS | WRITES


def answer_bank_key(digest):
    # Preserve all 256 bits while fitting owner_preferences.key VARCHAR(50).
    return "aa_ans:" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def reuse_key(value, step):
    from backend.app.services.application_question_classifier import (
        ApplicationQuestionClassifier,
    )

    classification = ApplicationQuestionClassifier().classify(step["question"])
    scope = [
        value["candidate_profile_id"],
        value["profile_version"],
        step["question"],
        step["answer_kind"],
        step["options"],
    ]
    if classification.question_type not in {
        "personal_details",
        "profile_link",
        "work_authorization",
    }:
        scope.append(
            {
                k: value["facts"].get(k)
                for k in (
                    "title",
                    "company",
                    "description",
                    "location",
                    "skills",
                    "experience_min",
                    "experience_max",
                    "salary_min",
                    "salary_max",
                )
            }
        )
    return answer_bank_key(
        hashlib.sha256(
            json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()
        ).digest()
    )


async def context(session, value, settings, *, writing=False):
    from backend.app.execution import naukri_identity, naukri_submission, naukri_upload
    from backend.app.execution.naukri_receipts import prevents_replay
    from backend.app.models.job import Job
    from backend.app.services.applications.service import ApplicationPacketService

    config = await queue.configuration(session)
    policy = QueuePolicy.model_validate(config["policy"])
    platform = policy.platforms["naukri"]
    if (
        config["state"] != "RUNNING"
        or not platform.enabled
        or not platform.owner_submission_authorized
        or platform.mode == "PREPARE_ONLY"
        or (await store.configuration(session)).mode == "OFF"
    ):
        raise ToolDenied("standing_submission_scope_required")
    await naukri_identity.check_work(session, value)
    if not any(
        a["fingerprint"].startswith("apply:") for a in value.get("admitted_actions", [])
    ):
        raise ToolDenied("questionnaire_requires_original_apply_admission")
    if await prevents_replay(session, value["requisition"]):
        raise ToolDenied("prior_receipt_requires_reconciliation_no_replay")
    packet = await ApplicationPacketService(session).read(UUID(value["packet_id"]))
    if (
        packet.lifecycle_state != "submitting"
        or packet.revision != value["packet_revision"]
        or packet.candidate_profile_version != value["profile_version"]
        or packet.readiness.stale
    ):
        raise ToolDenied("questionnaire_packet_context_changed")
    job = await session.get(Job, packet.job_id, populate_existing=True)
    if (
        not job
        or job.status in {"applied", "submitted", "archived"}
        or job.job_url != value["url"]
    ):
        raise ToolDenied("questionnaire_job_context_changed")
    profile = await queue.eligible_context(session, value, policy, job)
    checked = await naukri_upload.preflight(session, packet, settings)
    if (
        checked["state"] != "PDF_VERIFIED_LOCAL"
        or checked["sha256"] != value["upload_preflight"]["sha256"]
    ):
        raise ToolDenied("questionnaire_canonical_resume_changed")
    if writing:
        now = await instant(session)
        answer = value.get("questionnaire_answer", {})
        if (
            answer.get("answer_expires_at")
            and datetime.fromisoformat(answer["answer_expires_at"]) <= now
        ):
            raise ToolDenied("questionnaire_answer_expired")
        if answer.get("question_id"):
            q = await session.get(
                OwnerPreference,
                "exec_q:" + answer["question_id"],
                populate_existing=True,
            )
            if (
                not q
                or q.value.get("state") != "answered"
                or q.value.get("answer") != answer["answer"]
                or q.value.get("profile_version") != value["profile_version"]
                or (
                    answer.get("source") == "owner_approved_reuse"
                    and not q.value.get("reuse_approved")
                )
            ):
                raise ToolDenied("questionnaire_owner_answer_changed")
        if answer.get("project_digest"):
            from backend.app.browser.service import project_stamp

            if await project_stamp(session) != answer["project_digest"]:
                raise ToolDenied("questionnaire_grounded_context_changed")
        try:
            observed = datetime.fromisoformat(
                value["facts"]["provider_resume_checked_at"]
            )
            fresh_resume = timedelta(0) <= now - observed <= timedelta(minutes=2)
        except (KeyError, TypeError, ValueError):
            fresh_resume = False
        if not naukri_submission.account_current(value, now) or not fresh_resume:
            raise ToolDenied("questionnaire_fresh_profile_observation_required")
        original = value["form_binding"]
        if any(
            value["binding"].get(k) != original.get(k)
            for k in ("profile_binding_id", "browser_session_id", "window_id", "tab_id")
        ):
            raise ToolDenied("questionnaire_original_browser_context_required")
    return packet, profile


def descriptor(value):
    result = {
        "expected_account_sha256": value.get("account_sha256"),
        "expected_resume_sha256": value.get("upload_preflight", {}).get("sha256"),
        "account_observation": value.get("account_observation"),
        "expected_title": value.get("title"),
        "expected_company": value.get("company"),
    }
    if value["operation"] == "answer_questionnaire":
        step = value["questionnaire"]
        result["questionnaire"] = {
            "document_id": step["document_id"],
            "step_sha256": step["step_sha256"],
            "answer": value["questionnaire_answer"]["answer"],
            "permit_expires_at": value.get("permit_expires_at"),
        }
    return result


async def receive(session, value, report, settings):
    from backend.app.execution import naukri_submission as submission

    await context(session, value, settings)
    op, now = value["operation"], await instant(session)
    if report.kind in {"failed", "needs_input"}:
        # Even an answer/input event can submit. Never retry it to repair state.
        value.update(
            stage="SUBMISSION_UNKNOWN",
            status="unknown",
            reason=report.reason or "questionnaire_unconfirmed",
        )
        return
    if op == "refresh_questionnaire_profile":
        observed = report.execution
        if (
            report.kind != "execution_observation"
            or not observed
            or observed.state != "PROFILE_VERIFIED"
            or observed.account_sha256 != value["account_sha256"]
            or observed.resume_sha256 != value["upload_preflight"]["sha256"]
            or observed.resume_bytes != value["upload_preflight"]["byte_count"]
            or str(report.observed_url) != submission.PROFILE_URL
        ):
            raise ToolDenied("questionnaire_profile_observation_required")
        submission.retain_account_observation(value, observed, now)
        value["facts"] = {
            **value["facts"],
            "provider_resume_checked_at": now.isoformat(),
            "provider_resume_sha256": observed.resume_sha256,
            "provider_resume_source": "profile_download_ui",
        }
        value.update(
            operation="refresh_questionnaire_job", status="leased", stage="QUESTIONS"
        )
        return
    if op == "refresh_questionnaire_job":
        if (
            str(report.observed_url) != value["url"]
            or report.requisition != value["requisition"]
        ):
            raise ToolDenied("questionnaire_job_context_changed")
        if report.stage == "ALREADY_APPLIED":
            value.update(
                stage="VERIFYING",
                status="queued",
                operation="reconcile_application",
                reason="questionnaire_already_applied_reconcile_only",
            )
            return
        if report.kind != "job_facts" or not report.job:
            raise ToolDenied("questionnaire_fresh_job_facts_required")
        fresh = report.job.model_dump(mode="json")
        for field in (
            "requisition",
            "title",
            "company",
            "description",
            "location",
            "skills",
            "experience_min",
            "experience_max",
        ):
            if fresh.get(field) != value["facts"].get(field):
                raise ToolDenied("questionnaire_job_requirements_changed")
        value["facts"] = {**value["facts"], **fresh}
        await context(session, value, settings)
        value.update(
            operation="inspect_questionnaire", status="leased", stage="QUESTIONS"
        )
        return
    if (
        str(report.observed_url) != value["url"]
        or report.requisition != value["requisition"]
    ):
        raise ToolDenied("questionnaire_job_context_changed")
    if op == "inspect_questionnaire":
        step = report.questionnaire
        if report.kind != "questionnaire" or not step:
            raise ToolDenied("questionnaire_observation_required")
        expected_hash = hashlib.sha256(
            json.dumps(
                [value["url"], step.question, step.answer_kind, step.options],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if step.step_sha256 != expected_hash:
            raise ToolDenied("questionnaire_step_evidence_changed")
        if re.search(
            r"\b(email|e-mail|login|password|otp|consent|terms and conditions)\b",
            step.question,
            re.I,
        ):
            value.update(
                stage="NEEDS_INPUT",
                status="waiting",
                reason="questionnaire_identity_or_consent_requires_manual_review",
            )
            return
        if value.get("questionnaire_document_id") not in {None, step.document_id}:
            raise ToolDenied("questionnaire_original_document_required")
        value["questionnaire_document_id"] = step.document_id
        from backend.app.execution.questions import permitted

        try:
            permitted(step.question)
        except ToolDenied:
            value.update(
                stage="NEEDS_INPUT",
                status="waiting",
                reason="questionnaire_sensitive_input_requires_manual_review",
            )
            return
        if value.get("questionnaire_steps", 0) >= 20:
            raise ToolDenied("questionnaire_step_limit_reached")
        if any(
            a["fingerprint"] == "answer_questionnaire:" + step.step_sha256
            for a in value["admitted_actions"]
        ):
            value.update(
                stage="NEEDS_INPUT",
                status="waiting",
                reason="questionnaire_same_step_after_answer_requires_review",
            )
            return
        value["questionnaire"] = step.model_dump(mode="json")
        if value.get("questionnaire_answer"):
            answer = value["questionnaire_answer"]
            if answer.get("step_sha256") != step.step_sha256 or (
                answer.get("answer_expires_at")
                and datetime.fromisoformat(answer["answer_expires_at"]) <= now
            ):
                value.pop("questionnaire_answer", None)
            else:
                value.update(
                    stage="QUESTIONS",
                    status="leased",
                    operation="answer_questionnaire",
                    reason=None,
                    step_fingerprint=step.step_sha256,
                )
                return
        value.update(
            stage="QUESTIONS",
            status="queued",
            operation="prepare_questionnaire",
            reason=None,
        )
        return
    if op == "answer_questionnaire":
        step = value["questionnaire"]
        if (
            report.kind != "questionnaire_answer_attempted"
            or report.document_id != step["document_id"]
            or report.step_sha256 != step["step_sha256"]
        ):
            raise ToolDenied("questionnaire_answer_observation_required")
        value.update(
            stage="QUESTIONS",
            status="queued",
            operation="inspect_questionnaire",
            reason=None,
            questionnaire_steps=value.get("questionnaire_steps", 0) + 1,
        )
        value.pop("questionnaire_answer", None)
        return
    raise ToolDenied("questionnaire_operation_unsupported")


async def prepare_one(factory, settings):
    """Use the existing grounded answer engine outside a browser/owner transaction."""
    async with factory() as session, session.begin():
        pending = await session.scalar(
            select(OwnerPreference.key).where(
                OwnerPreference.key.startswith(queue.PREFIX),
                OwnerPreference.value["operation"].as_string()
                == "prepare_questionnaire",
                OwnerPreference.value["status"].as_string() == "queued",
            )
        )
        if not pending:
            return False
        value = await queue.claim(
            session,
            "naukri",
            {"worker": "questionnaire_preparation"},
            operations={"prepare_questionnaire"},
        )
        if not value:
            return False
        await context(session, value, settings)
        stamp = value["revision"], value["lease_token"]
    step = value["questionnaire"]
    answer, evidence = None, []
    answer_source, approved_question, answer_expiry, projects = (
        "grounded_saved_context",
        None,
        None,
        None,
    )
    known_fact_conflict = False
    async with factory() as session:
        bank = await session.get(OwnerPreference, reuse_key(value, step))
        now = await instant(session)
        if bank and datetime.fromisoformat(bank.value["answer_expires_at"]) > now:
            q = await session.get(
                OwnerPreference, "exec_q:" + bank.value["question_id"]
            )
            if (
                q
                and q.value.get("reuse_approved")
                and q.value.get("state") == "answered"
                and q.value["answer"] == bank.value["answer"]
            ):
                answer, approved_question, answer_expiry = (
                    bank.value["answer"],
                    bank.value["question_id"],
                    bank.value["answer_expires_at"],
                )
                answer_source = "owner_approved_reuse"
                evidence = [
                    {"source_type": "owner_answer", "source_id": approved_question}
                ]
        await session.rollback()
    if (
        not answer
        and step["answer_kind"] != "file"
        and not re.search(
            r"\b(email|e-mail|login|password|otp|consent|terms and conditions)\b",
            step["question"],
            re.I,
        )
    ):
        from backend.app.schemas.applications import QuestionInput
        from backend.app.schemas.candidate_profile import CandidateProfileRead
        from backend.app.services.application_answer_service import (
            ApplicationAnswerService,
        )
        from backend.app.services.application_question_classifier import (
            ApplicationQuestionClassifier,
        )
        from backend.app.services.applications.answer_builder import AnswerBuilder

        async with factory() as session:
            packet, profile = await context(session, value, settings)
            profile = CandidateProfileRead.model_validate(profile)
            packet_resume = packet.snapshot.resume
            from backend.app.browser.service import project_stamp

            projects = await project_stamp(session)
            await session.rollback()  # No owner lock or pooled lease during model work.
            kind = (
                ApplicationQuestionClassifier().classify(step["question"]).question_type
            )
            narrative = kind in {
                "project_explanation",
                "technical_experience",
                "short_text",
                "motivation",
                "startup_interest",
            }
            enabled_remote = (
                settings.COHERE_ENABLED and settings.COHERE_CANDIDATE_DATA_AUTHORIZED
            )
            # Scope the owner's Cohere authorization to this narrative answer.
            # Do not change the provider used by unrelated API/Telegram work.
            answer_settings = (
                settings.model_copy(update={"LLM_PROVIDER": "cohere"})
                if narrative and enabled_remote
                else settings
            )
            built = await AnswerBuilder(
                ApplicationAnswerService(
                    session, answer_settings, owns_read_transaction=True
                )
            ).build(
                QuestionInput(
                    question=step["question"],
                    field_type="multiple_choice" if step["options"] else "text",
                    options=step["options"],
                    required=True,
                    max_characters=step["max_characters"],
                ),
                UUID(value["job_id"]),
                profile,
                generate=not narrative or enabled_remote,
                rewrite=narrative and enabled_remote,
                resume=packet_resume,
            )
            known_fact_conflict = (
                built.provenance.source == "candidate_profile"
                and kind == "personal_details"
                and built.validation_status != "draft_ready"
            )
            if (
                built.validation_status == "draft_ready"
                and built.effective_answer
                and built.provenance.evidence_references
                and built.provenance.source
                in {
                    "candidate_profile",
                    "candidate_resource",
                    "approved_answer",
                    "owner_approved_exact_context",
                    "cohere",
                }
                and (
                    not narrative
                    or built.provenance.source
                    in {"approved_answer", "owner_approved_exact_context", "cohere"}
                )
            ):
                answer = built.effective_answer
                evidence = [
                    e.model_dump(mode="json")
                    for e in built.provenance.evidence_references
                ]
            await session.commit()
    async with factory() as session, session.begin():
        await store.memory_row(session, lock=True)
        row = await queue.load(session, value["id"])
        current = dict(row.value)
        if (current["revision"], current.get("lease_token")) != stamp or current[
            "status"
        ] != "leased":
            return False
        await context(session, current, settings)
        now = await instant(session)
        current.update(
            lease_token=None,
            lease_until=None,
            revision=current["revision"] + 1,
            updated_at=now.isoformat(),
        )
        if answer and (not step["options"] or answer in step["options"]):
            if projects:
                from backend.app.browser.service import project_stamp

                if await project_stamp(session) != projects:
                    raise ToolDenied("questionnaire_grounded_context_changed")
            current["questionnaire_answer"] = {
                "answer": answer,
                "evidence": evidence,
                "source": answer_source,
                "step_sha256": step["step_sha256"],
                "project_digest": projects,
                "question_id": approved_question,
                "answer_expires_at": answer_expiry,
            }
            current.update(
                operation="refresh_questionnaire_profile",
                stage="QUESTIONS",
                status="queued",
                reason=None,
            )
        else:
            current.update(
                stage="NEEDS_INPUT",
                status="waiting",
                reason="questionnaire_verified_answer_required",
            )
            if step["answer_kind"] == "file":
                current["reason"] = "questionnaire_supported_resume_attachment_required"
            elif known_fact_conflict:
                current["reason"] = "questionnaire_saved_fact_does_not_fit_controls"
            else:
                await ask(session, current, now)
        row.value = current
        await queue.event(session, current, "questionnaire_preparation_finished")
    return True


async def ask(session, value, now):
    from backend.app.execution import questions

    step = value["questionnaire"]
    questions.permitted(step["question"])
    identity = str(
        uuid5(
            NAMESPACE_URL,
            f"queue_question:{value['id']}:{value['packet_revision']}:{step['step_sha256']}",
        )
    )
    key = questions.PREFIX + identity
    if await session.get(OwnerPreference, key):
        return
    q = {
        "id": identity,
        "queue_work_id": value["id"],
        "execution_id": value["id"],
        "packet_id": value["packet_id"],
        "packet_revision": value["packet_revision"],
        "profile_version": value["profile_version"],
        "step_sha256": step["step_sha256"],
        "question": step["question"],
        "options": step["options"],
        "answer_type": "choice" if step["options"] else "text",
        "max_characters": step["max_characters"],
        "employer": value["company"],
        "role": value["title"],
        "job_url": value["url"],
        "state": "pending",
        "delivery_lease": None,
        "message_ids": [],
        "expired_message_ids": [],
        "expires_at": (now + timedelta(days=2)).isoformat(),
        "reuse_approved": False,
    }
    q["reuse_key"] = reuse_key(value, step)
    if len(questions.message_text(q)) > 4000:
        raise ToolDenied("telegram_question_too_long_manual_required")
    session.add(OwnerPreference(key=key, value=q))


async def question_current(session, q):
    try:
        row = await queue.load(session, q["queue_work_id"])
    except ToolDenied:
        return False
    v = row.value
    c = await queue.configuration(session)
    return (
        c["state"] == "RUNNING"
        and v["stage"] == "NEEDS_INPUT"
        and v["status"] == "waiting"
        and v.get("questionnaire", {}).get("step_sha256") == q["step_sha256"]
        and v["packet_id"] == q["packet_id"]
        and v["packet_revision"] == q["packet_revision"]
        and v["profile_version"] == q["profile_version"]
    )


async def answer_question(session, qrow, answer, now, settings):
    from backend.app.execution import questions

    q = dict(qrow.value)
    if not await question_current(session, q):
        raise ToolDenied("questionnaire_question_context_changed")
    expiry = questions.validate(q, answer, now)
    row = await queue.load(session, q["queue_work_id"])
    v = dict(row.value)
    await context(session, v, settings)
    q.update(
        state="answered",
        answer=answer,
        answer_expires_at=expiry,
        reuse_approved=False,
        provenance={"source": "owner_telegram", "application_only": True},
    )
    qrow.value = q
    v["questionnaire_answer"] = {
        "answer": answer,
        "source": "owner_telegram",
        "question_id": q["id"],
        "answer_expires_at": expiry,
        "step_sha256": q["step_sha256"],
    }
    v.update(
        stage="QUESTIONS",
        status="queued",
        operation="refresh_questionnaire_profile",
        reason=None,
        revision=v["revision"] + 1,
        available_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    row.value = v
    await queue.event(session, v, "questionnaire_owner_answer_saved_refresh_required")
    return "Answer saved for this application. The worker will refresh its account, resume, job and original form checks before continuing. No second Apply is authorized."


async def approve_reuse(session, row):
    from backend.app.services.applications.service import ApplicationPacketService

    q, now = dict(row.value), await instant(session)
    packet = await ApplicationPacketService(session).read(UUID(q["packet_id"]))
    if (
        q["state"] != "answered"
        or datetime.fromisoformat(q["answer_expires_at"]) <= now
        or packet.readiness.stale
        or packet.candidate_profile_version != q["profile_version"]
    ):
        raise ToolDenied("answer_context_stale")
    key = q["reuse_key"]
    legacy = re.fullmatch(r"apply_answer_bank:([0-9a-f]{64})", key)
    if legacy:
        # Questions may already contain the old oversized key in their JSON.
        # PostgreSQL could never persist a bank row under that VARCHAR(50) key.
        key = answer_bank_key(bytes.fromhex(legacy.group(1)))
    elif not re.fullmatch(r"aa_ans:[A-Za-z0-9_-]{43}", key):
        raise ToolDenied("answer_context_stale")
    row.value = {**q, "reuse_key": key, "reuse_approved": True}
    await queue.put(
        session,
        key,
        {
            "answer": q["answer"],
            "question_id": q["id"],
            "profile_version": q["profile_version"],
            "answer_expires_at": q["answer_expires_at"],
        },
    )
    return row.value
