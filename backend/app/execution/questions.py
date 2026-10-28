"""Owner-only reply correlation, durable delivery, expiry and opt-in reuse."""

import re
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.knowledge.missing_input import permitted as permit_answer
from backend.app.models.application_packet import ApplicationPacketField
from backend.app.repositories.candidate_profile import ProfileConflictError
from backend.app.schemas.applications import AnswerEdit
from backend.app.services.applications.service import ApplicationPacketService

PREFIX = "exec_q:"


def permitted(question, answer=""):
    try:
        permit_answer(question, answer)
    except ProfileConflictError:
        raise ToolDenied("sensitive_answer_not_retained") from None


def answer_type(field):
    if re.search(
        r"interview|availability|available.*(?:week|date)", field.question, re.I
    ):
        return "availability"
    return "choice" if field.options or field.field_type == "yes_no" else "text"


def field_answer(question, answer):
    return (
        answer.partition(" | ")[0]
        if question["answer_type"] == "availability" and question["options"]
        else answer
    )


def validate(question, answer, now):
    permitted(question["question"], answer)
    value = field_answer(question, answer)
    if not value.strip() or len(value) > question["max_characters"]:
        raise ToolDenied("answer_length_invalid")
    if question["options"] and value not in question["options"]:
        raise ToolDenied("answer_must_match_option")
    if (
        question["answer_type"] == "choice"
        and not question["options"]
        and answer.casefold() not in {"yes", "no"}
    ):
        raise ToolDenied("yes_or_no_required")
    if question["answer_type"] == "availability":
        if question["options"] and value.casefold() == "no" and answer == value:
            return (now + timedelta(days=7)).isoformat()
        slot = answer.partition(" | ")[2] if question["options"] else answer
        try:
            stamp, zone = slot.split()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", stamp):
                raise ValueError
            local = datetime.fromisoformat(stamp)
            if local.tzinfo is not None:
                raise ValueError
            tz = ZoneInfo(zone)
            scheduled = local.replace(tzinfo=tz)
            if scheduled.utcoffset() != local.replace(tzinfo=tz, fold=1).utcoffset():
                raise ValueError
            if scheduled <= now or scheduled > now + timedelta(days=90):
                raise ValueError
            return (
                min(scheduled, now + timedelta(days=7))
                .astimezone(timezone.utc)
                .isoformat()
            )
        except (ValueError, ZoneInfoNotFoundError):
            raise ToolDenied(
                "availability_requires_future_datetime_and_iana_timezone"
            ) from None
    return (
        now
        + timedelta(
            days=7
            if re.search(r"salary|relocat|authoriz", question["question"], re.I)
            else 30
        )
    ).isoformat()


async def ask(session, execution_id, field_id):
    await store.memory_row(session, lock=True)
    execution = await store.load(session, execution_id)
    if (
        execution.value["state"] not in {"NEEDS_INPUT", "READY_FOR_REVIEW", "FILLING"}
        or not execution.value["packet_id"]
    ):
        raise ToolDenied("execution_not_waiting_for_question")
    packet = await ApplicationPacketService(session).read(
        UUID(execution.value["packet_id"])
    )
    if packet.readiness.stale:
        raise ToolDenied("packet_context_stale")
    field = next((f for f in packet.fields if f.id == field_id), None)
    if field is None or field.field_type == "file":
        raise ToolDenied("answerable_packet_field_required")
    permitted(field.question)
    identity = str(
        uuid5(
            NAMESPACE_URL,
            f"{execution_id}:{field_id}:{packet.revision}:{packet.snapshot.context_digest}",
        )
    )
    row = await session.get(OwnerPreference, PREFIX + identity)
    now = await instant(session)
    if row:
        if (
            row.value["state"] in {"pending", "sent"}
            and row.value["expires_at"] <= now.isoformat()
        ):
            row.value = {
                **row.value,
                "state": "pending",
                "delivery_lease": None,
                "expired_message_ids": [
                    *row.value.get("expired_message_ids", []),
                    *row.value["message_ids"],
                ][-50:],
                "message_ids": [],
                "expires_at": (now + timedelta(days=2)).isoformat(),
            }
            if execution.value["state"] != "NEEDS_INPUT":
                await store.move(
                    session, execution, "NEEDS_INPUT", "owner_reconfirmation_required"
                )
        return row.value
    value = {
        "id": identity,
        "execution_id": str(execution_id),
        "packet_id": str(packet.id),
        "field_id": str(field.id),
        "packet_revision": packet.revision,
        "profile_version": packet.candidate_profile_version,
        "context_digest": packet.snapshot.context_digest,
        "question": field.question,
        "options": field.options,
        "answer_type": answer_type(field),
        "max_characters": field.max_characters,
        "employer": packet.snapshot.company_name,
        "role": packet.snapshot.job_title,
        "job_url": execution.value["normalized_url"],
        "state": "pending",
        "message_ids": [],
        "answer": None,
        "reuse_approved": False,
        "answer_expires_at": None,
        "expires_at": (now + timedelta(days=2)).isoformat(),
        "delivery_lease": None,
    }
    if len(message_text(value)) > 4000:
        raise ToolDenied("telegram_question_too_long_manual_required")
    session.add(OwnerPreference(key=PREFIX + identity, value=value))
    if execution.value["state"] != "NEEDS_INPUT":
        await store.move(session, execution, "NEEDS_INPUT", "waiting_for_owner_answer")
    return value


def message_text(q):
    hint = (
        "YYYY-MM-DDTHH:MM Area/City (for example Asia/Kolkata)"
        if q["answer_type"] == "availability"
        else " / ".join(q["options"]) or q["answer_type"]
    )
    if q["answer_type"] == "availability" and q["options"]:
        hint = (
            "exact option + ' | ' + date/time/time zone, or No. Options: "
            + " / ".join(q["options"])
        )
    return (
        f"{q['employer']} — {q['role']}\nQuestion: {q['question']}\n"
        f"Application: {q['execution_id']}\n{q['job_url']}\nExpected: {hint}\n"
        "Reply to THIS message with your verified factual answer. This answers only this application; reuse needs separate approval. A fresh form review is required before filling."
    )


async def receive(session, settings, message, update_id):
    from backend.app.local_agent.telegram import authorized

    if not authorized(message, settings):
        raise ToolDenied("telegram_owner_required")
    reply_id = message.get("reply_to_message", {}).get("message_id")
    if type(reply_id) is not int:
        return None
    await store.memory_row(session, lock=True)
    candidates = (
        await session.scalars(
            select(OwnerPreference).where(OwnerPreference.key.startswith(PREFIX))
        )
    ).all()
    row = next((r for r in candidates if reply_id in r.value["message_ids"]), None)
    if row is None:
        if any(reply_id in r.value.get("expired_message_ids", []) for r in candidates):
            return "This question expired. Reply to the latest question message to reconfirm."
        return None
    q, now = dict(row.value), await instant(session)
    if q["state"] == "answered":
        return "This question was already answered. Review the saved application before changing it."
    execution = await store.load(session, q["execution_id"])
    if (
        q["expires_at"] <= now.isoformat()
        or execution.value["state"] != "NEEDS_INPUT"
        or execution.value.get("cancelled")
    ):
        return "This question expired or its application is paused/cancelled. Review the current application."
    answer = message.get("text", "").strip()
    try:
        expiry = validate(q, answer, now)
    except (ToolDenied, ValueError) as error:
        return "Answer rejected: " + str(error)
    service = ApplicationPacketService(session)
    packet = await service.read(UUID(q["packet_id"]))
    if (
        packet.revision != q["packet_revision"]
        or packet.snapshot.context_digest != q["context_digest"]
        or packet.readiness.stale
    ):
        return "Application context changed. Review the current form and ask a new question."
    updated = await service.edit_answer(
        packet.id,
        UUID(q["field_id"]),
        AnswerEdit(expected_revision=packet.revision, answer=field_answer(q, answer)),
    )
    field = await session.get(ApplicationPacketField, UUID(q["field_id"]))
    field.provenance = {
        **field.provenance,
        "telegram_owner_update": update_id,
        "telegram_question": q["id"],
        "answer_expires_at": expiry,
        "interview_availability": answer
        if q["answer_type"] == "availability"
        else None,
    }
    q.update(
        state="answered",
        answer_revision=field.answer_revision,
        answer=field_answer(q, answer),
        factual_context=answer,
        answer_expires_at=expiry,
        provenance={
            "channel": "telegram",
            "owner_user_id": settings.TELEGRAM_OWNER_USER_ID,
            "update_id": update_id,
            "reply_message_id": reply_id,
        },
    )
    row.value = q
    execution.value = {
        **execution.value,
        "answer_revisions": {
            **execution.value.get("answer_revisions", {}),
            q["field_id"]: field.answer_revision,
        },
    }
    # An answer to one field advances only sibling envelopes in this exact packet.
    waiting = False
    for sibling in candidates:
        v = sibling.value
        if (
            v["id"] != q["id"]
            and v["packet_id"] == q["packet_id"]
            and v["state"] in {"pending", "sent"}
            and v["packet_revision"] == packet.revision
        ):
            sibling.value = {**v, "packet_revision": updated.revision}
            waiting = True
    if not waiting:
        await store.move(
            session, execution, "PREPARING", "owner_answer_saved_fresh_review_required"
        )
    return f"Answer saved for {q['employer']} — {q['role']}. Application {q['execution_id']}. Reuse is OFF. Approve exact-context reuse in the dashboard. Review before filling."


async def answer_dashboard(session, question_id, answer):
    await store.memory_row(session, lock=True)
    row = await session.get(
        OwnerPreference, PREFIX + str(question_id), populate_existing=True
    )
    if not row:
        raise ToolDenied("question_not_found")
    q, now = dict(row.value), await instant(session)
    if q["state"] == "answered":
        raise ToolDenied("question_already_answered")
    execution = await store.load(session, q["execution_id"])
    if (
        q["expires_at"] <= now.isoformat()
        or execution.value["state"] != "NEEDS_INPUT"
        or execution.value.get("cancelled")
    ):
        raise ToolDenied("question_expired_or_application_cancelled")
    answer = answer.strip()
    expiry = validate(q, answer, now)
    service = ApplicationPacketService(session)
    packet = await service.read(UUID(q["packet_id"]))
    if (
        packet.revision != q["packet_revision"]
        or packet.snapshot.context_digest != q["context_digest"]
        or packet.readiness.stale
    ):
        raise ToolDenied("packet_context_stale")
    updated = await service.edit_answer(
        packet.id,
        UUID(q["field_id"]),
        AnswerEdit(expected_revision=packet.revision, answer=field_answer(q, answer)),
    )
    field = await session.get(ApplicationPacketField, UUID(q["field_id"]))
    field.provenance = {
        **field.provenance,
        "dashboard_owner_answer": True,
        "telegram_question": q["id"],
        "answer_expires_at": expiry,
        "interview_availability": answer
        if q["answer_type"] == "availability"
        else None,
    }
    q.update(
        state="answered",
        answer_revision=field.answer_revision,
        answer=field_answer(q, answer),
        factual_context=answer,
        answer_expires_at=expiry,
        provenance={
            "channel": "dashboard",
            "source": "owner_dashboard",
        },
    )
    row.value = q
    execution.value = {
        **execution.value,
        "answer_revisions": {
            **execution.value.get("answer_revisions", {}),
            q["field_id"]: field.answer_revision,
        },
    }
    candidates = (
        await session.scalars(
            select(OwnerPreference).where(OwnerPreference.key.startswith(PREFIX))
        )
    ).all()
    waiting = False
    for sibling in candidates:
        v = sibling.value
        if (
            v["id"] != q["id"]
            and v["packet_id"] == q["packet_id"]
            and v["state"] in {"pending", "sent"}
            and v["packet_revision"] == packet.revision
        ):
            sibling.value = {**v, "packet_revision": updated.revision}
            waiting = True
    if not waiting:
        await store.move(
            session, execution, "PREPARING", "owner_answer_saved_fresh_review_required"
        )
    return row.value


async def approve_reuse(session, question_id):
    await store.memory_row(session, lock=True)
    row = await session.get(
        OwnerPreference, PREFIX + str(question_id), populate_existing=True
    )
    now = await instant(session)
    if (
        not row
        or row.value["state"] != "answered"
        or row.value["answer_expires_at"] <= now.isoformat()
    ):
        raise ToolDenied("current_answer_required")
    packet = await ApplicationPacketService(session).read(UUID(row.value["packet_id"]))
    if (
        packet.readiness.stale
        or packet.candidate_profile_version != row.value["profile_version"]
    ):
        raise ToolDenied("answer_context_stale")
    field = next((f for f in packet.fields if str(f.id) == row.value["field_id"]), None)
    if (
        not field
        or field.effective_answer != row.value["answer"]
        or field.answer_revision != row.value.get("answer_revision")
    ):
        raise ToolDenied("answer_changed_review_again")
    row.value = {**row.value, "reuse_approved": True}
    return row.value


async def deliver_one(factory, settings, bot):
    """At-least-once notification; reply IDs persist. Never retries applications."""
    if not settings.TELEGRAM_OWNER_USER_ID or not settings.TELEGRAM_OWNER_CHAT_ID:
        return False
    async with factory() as session, session.begin():
        await store.memory_row(session, lock=True)
        now = await instant(session)
        qs = (
            await session.scalars(
                select(OwnerPreference)
                .where(OwnerPreference.key.startswith(PREFIX))
                .order_by(OwnerPreference.created_at)
            )
        ).all()
        row = None
        for candidate in qs:
            v = candidate.value
            if (
                v["state"] != "pending"
                or v["expires_at"] <= now.isoformat()
                or (v["delivery_lease"] and v["delivery_lease"] > now.isoformat())
            ):
                continue
            execution = await store.load(session, v["execution_id"])
            if execution.value["state"] == "NEEDS_INPUT":
                row = candidate
                break
        if row is None:
            return False
        q = dict(row.value)
        row.value = {**q, "delivery_lease": (now + timedelta(seconds=60)).isoformat()}
    result = await bot.call(
        "sendMessage",
        {
            "chat_id": settings.TELEGRAM_OWNER_CHAT_ID,
            "text": message_text(q),
            "reply_markup": {"force_reply": True, "selective": True},
            "link_preview_options": {"is_disabled": True},
        },
    )
    if type(result.get("message_id")) is not int:
        from backend.app.local_agent.telegram import TelegramError

        raise TelegramError("telegram_message_receipt_required")
    async with factory() as session, session.begin():
        await store.memory_row(session, lock=True)
        row = await session.get(
            OwnerPreference, PREFIX + q["id"], populate_existing=True
        )
        row.value = {
            **row.value,
            "state": "sent" if row.value["state"] == "pending" else row.value["state"],
            "message_ids": [*row.value["message_ids"], result["message_id"]],
            "delivery_lease": None,
        }
    return True


async def bridge_form(session, packet, plan):
    """Persist actual unanswered form questions before queueing owner messages.

    Caller holds the owner lock before locking packet context. Native DOM field
    references are deliberately not reused after the answer; a new inspection
    and explicit field review bind the current document.
    """
    from backend.app.execution.naukri import normalized_url
    from backend.app.schemas.applications import QuestionInput, QuestionsAdd

    try:
        normalized_url(packet.snapshot.original_job_url)
    except ValueError:
        return packet
    unresolved = {a.field_id for a in plan.actions if a.needs_input}
    envelopes = []
    for field in plan.inspection.fields:
        if (
            not field.required
            or field.field_id not in unresolved
            or field.kind == "file"
        ):
            continue
        question = field.group_label or field.label
        try:
            permitted(question)
        except ValueError:
            continue
        existing = next((f for f in packet.fields if f.question == question), None)
        if existing is None:
            packet = await ApplicationPacketService(session).add_questions(
                packet.id,
                QuestionsAdd(
                    expected_revision=packet.revision,
                    questions=[
                        QuestionInput(
                            question=question,
                            field_type="multiple_choice" if field.options else "text",
                            options=field.options,
                            max_characters=field.max_length,
                        )
                    ],
                ),
            )
            existing = next(f for f in packet.fields if f.question == question)
        intent = (await store.start(session, [packet.job_id]))[0]
        execution = await store.load(session, intent["id"])
        if execution.value["state"] in store.TERMINAL | {"PAUSED"}:
            continue
        execution.value = {
            **execution.value,
            "packet_id": str(packet.id),
            "state": "NEEDS_INPUT",
            "lease_until": None,
            "fence": execution.value["fence"] + 1,
        }
        envelope = await ask(session, intent["id"], existing.id)
        envelopes.append(envelope["id"])
    await session.flush()
    for identity in envelopes:
        row = await session.get(OwnerPreference, PREFIX + identity)
        row.value = {**row.value, "packet_revision": packet.revision}
    plan.packet_revision = packet.revision
    return packet


async def reuse_for(session, source_id, execution_id, field_id):
    """Copy a separately approved answer only into a compatible reviewable draft."""
    await store.memory_row(session, lock=True)
    source = await session.get(OwnerPreference, PREFIX + str(source_id))
    now = await instant(session)
    if (
        not source
        or not source.value["reuse_approved"]
        or source.value["answer_expires_at"] <= now.isoformat()
    ):
        raise ToolDenied("unexpired_reuse_approval_required")
    q = source.value
    original = await ApplicationPacketService(session).read(UUID(q["packet_id"]))
    source_field = next(
        (f for f in original.fields if str(f.id) == q["field_id"]), None
    )
    if (
        original.readiness.stale
        or not source_field
        or source_field.effective_answer != q["answer"]
        or source_field.answer_revision != q.get("answer_revision")
    ):
        raise ToolDenied("source_answer_changed_review_again")
    execution = await store.load(session, execution_id)
    if execution.value["state"] not in {"NEEDS_INPUT", "READY_FOR_REVIEW"}:
        raise ToolDenied("execution_not_waiting_for_question")
    service = ApplicationPacketService(session)
    packet = await service.read(UUID(execution.value["packet_id"]))
    field = next((f for f in packet.fields if f.id == field_id), None)
    from backend.app.models.job import Job

    source_execution = await store.load(session, q["execution_id"])
    original_job = await session.get(Job, UUID(source_execution.value["job_id"]))
    target_job = await session.get(Job, packet.job_id)
    if (
        not field
        or packet.readiness.stale
        or packet.candidate_profile_version != q["profile_version"]
        or packet.snapshot.company_name != q["employer"]
        or packet.snapshot.job_title != q["role"]
        or field.question != q["question"]
        or field.options != q["options"]
        or original_job.description != target_job.description
    ):
        raise ToolDenied("answer_reuse_context_mismatch")
    updated = await service.edit_answer(
        packet.id,
        field_id,
        AnswerEdit(expected_revision=packet.revision, answer=q["answer"]),
    )
    saved = await session.get(ApplicationPacketField, field_id)
    saved.provenance = {
        **saved.provenance,
        "telegram_question": q["id"],
        "answer_expires_at": q["answer_expires_at"],
    }
    return updated
