"""Durable Chrome packet/tab ownership. No page data can grant execution rights.

The owner row serializes bindings across packets. Chrome's local session UUID
scopes tab IDs; a restart invalidates authorization instead of replaying writes.
"""

import hashlib
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field
from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.browser.contracts import Contract
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.local_agent.models import AgentOperation

PREFIX = "ext_task:"
TASK_COMMANDS = {
    "open_application_task", "get_application_task", "update_application_task", "ask_form_questions",
}
TERMINAL = {"FAILED_FINAL", "SUBMISSION_UNKNOWN", "SUBMITTED_CONFIRMED"}
CHALLENGE_SAFE = {"NONE", "MANUALLY_RESOLVED_AND_SITE_VERIFIED"}
NEXT = {
    "PACKET_READY": "Inspect this application step and review its answers.",
    "FORM_INSPECTED": "Prepare and review answers for this step.",
    "NEEDS_INPUT": "Answer the saved questions, then inspect and review this step again.",
    "ANSWERS_REVIEWED": "Authorize the exact reviewed fields in the extension.",
    "FILL_AUTHORIZED": "Fill only the approved fields in the bound tab.",
    "FILLING": "Wait for retained-value verification, or pause to take over.",
    "FILLED_VERIFIED": "Review the retained values and remaining manual fields on the site.",
    "READY_FOR_SUBMISSION": "Review the complete application on the site; submission is owner-operated.",
    "PAUSED": "Resume, inspect the current step and authorize fresh fields.",
    "FAILED_RETRYABLE": "Check the connection and current tab, then resume with a fresh inspection.",
    "FAILED_FINAL": "This task was cancelled or ended. Open a new reviewed task if needed.",
    "CHALLENGE_REQUIRED": "Complete the challenge manually. Fresh site verification, inspection and review are required.",
    "SUBMISSION_UNKNOWN": "Check the employer receipt manually. Do not retry submission.",
    "SUBMITTED_CONFIRMED": "Check the independently confirmed submission receipt.",
}


class TaskControl(Contract):
    action: Literal["pause", "resume", "cancel"]
    expected_version: int = Field(ge=1)


class TaskCounts(Contract):
    ready: int = 0
    completed: int = 0
    missing: int = 0
    manual: int = 0
    validation_errors: int = 0
    existing: int = 0


class TaskCapabilities(Contract):
    preview: Literal[True] = True
    assisted_fill: bool = False
    reviewed_submission: Literal[False] = False
    unattended_approved: Literal[False] = False


class ExtensionTask(Contract):
    id: UUID
    version: int
    application_id: UUID
    job_id: UUID
    company_name: str | None
    job_title: str
    packet_revision: int
    profile_version: int
    context_digest: str
    target_url: str
    current_url: str
    browser_session_id: UUID
    profile_binding_id: UUID | None = None
    window_id: int | None = None
    tab_id: int | None
    state: Literal["DISCOVERED", "PACKET_READY", "FORM_INSPECTED", "NEEDS_INPUT", "ANSWERS_REVIEWED", "FILL_AUTHORIZED", "FILLING", "FILLED_VERIFIED", "READY_FOR_SUBMISSION", "PAUSED", "FAILED_RETRYABLE", "FAILED_FINAL", "CHALLENGE_REQUIRED", "SUBMISSION_UNKNOWN", "SUBMITTED_CONFIRMED"]
    challenge_state: Literal["NONE", "WIDGET_PRESENT_UNVERIFIED", "CHALLENGE_BLOCKING", "MANUALLY_RESOLVED_AND_SITE_VERIFIED", "UNKNOWN"]
    step: str | None
    plan_id: UUID | None
    authorization_id: UUID | None
    field_answer_revisions: dict[str, int]
    verified_receipts: list[dict]
    reason: str | None
    next_action: str
    mode: Literal["ASSISTED_FILL"]
    capabilities: TaskCapabilities
    counts: TaskCounts
    browser_connection: Literal["connected", "paused", "disconnected", "unverified"]
    tab_active: bool
    challenge_observed: bool = False
    network_guard_active: bool = False
    updated_at: str


def now():
    return datetime.now(timezone.utc).isoformat()


async def rows(session):
    await session.flush()
    return list((await session.scalars(
        select(OwnerPreference).where(OwnerPreference.key.startswith(PREFIX))
        .order_by(OwnerPreference.created_at.desc())
        .execution_options(populate_existing=True)
    )).all())


async def load(session, task_id):
    await session.flush()
    row = await session.get(OwnerPreference, PREFIX + str(UUID(str(task_id))), populate_existing=True)
    if row is None:
        raise ToolDenied("extension_task_not_found")
    return row


async def by_application(session, application_id):
    identity = uuid5(NAMESPACE_URL, "extension_task:" + str(application_id))
    row = await session.get(OwnerPreference, PREFIX + str(identity))
    return row.value if row else None


def move(session, row, state, reason, **changes):
    value = {
        **row.value, **changes, "state": state, "reason": reason,
        "next_action": NEXT[state], "version": row.value["version"] + 1,
        "updated_at": now(),
    }
    row.value = value
    session.add(AgentOperation(
        key=f"extension:{value['id']}:{value['version']}", actor="owner:primary",
        command="extension_task:" + state.lower(),
        payload_hash=hashlib.sha256(f"{value['id']}:{value['version']}:{reason}".encode()).hexdigest(),
        result={"task_id": value["id"], "application_id": value["application_id"],
                "state": state, "reason": reason, "version": value["version"], "submitted": False},
    ))
    return value


async def fresh(session, settings, value):
    from backend.app.browser.service import FormService
    packet, profile, url = await FormService(session, settings).context(UUID(value["application_id"]), "manual_extension")
    if (packet.revision != value["packet_revision"]
        or profile.version != value["profile_version"]
        or packet.snapshot.context_digest != value["context_digest"]
        or url != value["target_url"]):
        raise ToolDenied("extension_task_context_stale")
    return packet


async def create(session, settings, application_id, browser_session_id, tab_id=None, profile_binding_id=None, window_id=None, expected_version=None):
    from backend.app.browser.service import FormService
    if not browser_session_id:
        raise ToolDenied("browser_session_required")
    await store.memory_row(session, lock=True)
    packet, profile, url = await FormService(session, settings).context(application_id, "manual_extension")
    identity = uuid5(NAMESPACE_URL, "extension_task:" + str(application_id))
    existing = await session.get(OwnerPreference, PREFIX + str(identity), populate_existing=True)
    if existing:
        if expected_version is not None and expected_version != existing.value["version"]:
            raise ToolDenied("extension_task_revision_conflict")
        if existing.value["state"] in TERMINAL:
            raise ToolDenied("extension_task_terminal")
        if existing.value.get("profile_binding_id") != str(profile_binding_id):
            # Explicit Open in the newly selected profile is the only transfer gesture.
            # Selection/disconnect has already paused the old task and revoked plans.
            if existing.value["state"] != "PAUSED":
                raise ToolDenied("PROFILE_NOT_SELECTED")
            paused = existing.value.get("reason") in {"owner_pause", "global_stop"}
            move(session, existing, "PAUSED" if paused else "PACKET_READY", existing.value["reason"] if paused else "owner_profile_transfer",
                 profile_binding_id=str(profile_binding_id), browser_session_id=str(browser_session_id),
                 window_id=window_id, tab_id=None, tab_active=False, plan_id=None,
                 authorization_id=None, network_guard_active=False, browser_connection="unverified",
                 counts={"ready": 0, "completed": 0, "missing": 0, "manual": 0, "validation_errors": 0, "existing": 0},
                 step=None, challenge_state="UNKNOWN")
        if existing.value["browser_session_id"] != str(browser_session_id):
            raise ToolDenied("extension_task_recovery_required")
        # Reopening a popup or duplicate click cannot create another task or refresh permissions.
        return existing
    for other in await rows(session):
        if other.value["job_id"] == str(packet.job_id) and other.value["state"] not in TERMINAL:
            raise ToolDenied("extension_job_already_owned")
    if tab_id is not None:
        await unclaimed(session, identity, browser_session_id, tab_id)
    row = OwnerPreference(key=PREFIX + str(identity), value={
        "id": str(identity), "version": 1, "application_id": str(application_id),
        "job_id": str(packet.job_id), "company_name": packet.snapshot.company_name,
        "job_title": packet.snapshot.job_title, "packet_revision": packet.revision,
        "profile_version": profile.version, "context_digest": packet.snapshot.context_digest,
        "target_url": url, "current_url": url, "browser_session_id": str(browser_session_id),
        "profile_binding_id": str(profile_binding_id), "window_id": window_id,
        "tab_id": tab_id, "state": "PACKET_READY", "challenge_state": "UNKNOWN",
        "step": None, "plan_id": None, "authorization_id": None,
        "field_answer_revisions": {str(f.id): f.answer_revision for f in packet.fields},
        "verified_receipts": [], "network_guard_active": False, "reason": None, "next_action": NEXT["PACKET_READY"],
        "mode": "ASSISTED_FILL", "capabilities": {"preview": True,
            "assisted_fill": bool(settings.BROWSER_FILL_ENABLED),
            "reviewed_submission": False, "unattended_approved": False},
        "counts": {"ready": 0, "completed": 0, "missing": 0, "manual": 0, "validation_errors": 0, "existing": 0},
        "browser_connection": "connected" if tab_id is not None else "unverified",
        "tab_active": tab_id is not None, "challenge_observed": False, "updated_at": now(),
    })
    session.add(row)
    await session.flush()
    return row


async def unclaimed(session, task_id, browser_session_id, tab_id):
    for other in await rows(session):
        value = other.value
        if (value["id"] != str(task_id) and value["state"] not in TERMINAL
            and value["browser_session_id"] == str(browser_session_id)
            and value["tab_id"] == tab_id):
            raise ToolDenied("extension_tab_already_owned")


async def bound(session, command, *, require_plan=False, allow_background_inspection=False):
    await store.memory_row(session, lock=True)
    if not command.task_id:
        raise ToolDenied("extension_task_required")
    row = await load(session, command.task_id)
    value = row.value
    if value.get("profile_binding_id") != str(command.profile_binding_id):
        raise ToolDenied("PROFILE_NOT_SELECTED")
    if command.expected_task_version != value["version"]:
        raise ToolDenied("extension_task_revision_conflict")
    if (not command.browser_session_id
        or value["browser_session_id"] != str(command.browser_session_id)
        or command.tab_id is None or command.tab_id != value["tab_id"]
        or command.window_id is None or command.window_id != value.get("window_id")):
        raise ToolDenied("extension_tab_binding_mismatch")
    focus_only = (allow_background_inspection and value["state"] == "PAUSED"
                  and value.get("reason") in {"focus_lost", "active_tab_changed"})
    if value["state"] in TERMINAL or (value["state"] == "PAUSED" and not focus_only):
        raise ToolDenied("extension_task_paused_or_cancelled")
    if require_plan and str(command.plan_id or (command.receipt.plan_id if command.receipt else "")) != value["plan_id"]:
        raise ToolDenied("extension_task_plan_mismatch")
    return row


async def attach_plan(session, settings, row, plan):
    from backend.app.browser.service import FormService
    value = row.value
    if (str(plan.application_id) != value["application_id"] or plan.target_url != value["current_url"]
        or plan.state not in {"preview", "read_only"}):
        raise ToolDenied("extension_task_plan_mismatch")
    await FormService(session, settings).fresh(plan)
    if plan.extension_task_id and str(plan.extension_task_id) != value["id"]:
        raise ToolDenied("extension_task_plan_mismatch")
    plan.extension_task_id = UUID(value["id"])
    # Reloading removes a document-local sticky observation; absence in a new
    # document is never evidence that a prior security challenge was completed.
    if value.get("challenge_observed") and plan.inspection.challenge_state == "NONE":
        plan.inspection.challenge_state = "UNKNOWN"
        plan.state = "read_only"
    saved, _ = await FormService(session, settings).load(plan.id)
    saved.value = plan.model_dump(mode="json")
    challenge = plan.inspection.challenge_state
    state = ("CHALLENGE_REQUIRED" if challenge not in CHALLENGE_SAFE else
             "NEEDS_INPUT" if plan.state == "read_only" or any(a.needs_input for a in plan.actions) else "FORM_INSPECTED")
    packet, profile, _ = await FormService(session, settings).context(plan.application_id, "manual_extension")
    return move(session, row, state, "fresh_inspection_prepared", plan_id=str(plan.id), authorization_id=None,
        packet_revision=packet.revision, profile_version=profile.version, context_digest=packet.snapshot.context_digest,
        step=next((f.page_step for f in plan.inspection.fields if f.page_step), None),
        challenge_state=challenge,
        challenge_observed=value.get("challenge_observed", False) or challenge in {"WIDGET_PRESENT_UNVERIFIED", "CHALLENGE_BLOCKING"},
        field_answer_revisions={str(f.id): f.answer_revision for f in packet.fields},
        counts={"ready": sum(not a.needs_input and not a.preview_only and a.kind != "file" for a in plan.actions),
                "completed": 0,
                "missing": sum(a.needs_input for a in plan.actions),
                "manual": sum(a.preview_only or a.kind == "file" for a in plan.actions) + len({c.control_id for c in plan.inspection.manual_controls}),
                "validation_errors": sum(f.invalid for f in plan.inspection.fields) + sum(c.invalid for c in plan.inspection.manual_controls),
                "existing": plan.inspection.completed_count},
        browser_connection="connected", tab_active=True,
        **({"next_action": "Complete unsupported page interactions manually. This plan is read-only; a fresh inspection and review are required."}
           if plan.state == "read_only" and challenge in CHALLENGE_SAFE else {}))


def permitted_navigation(value, url):
    # Navigation is only an observation. Never authorize redirects by same-origin alone.
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        return None
    if parsed.netloc != urlsplit(value["target_url"]).netloc:
        return None
    if url != value["target_url"]:
        return None
    return url


async def update(session, settings, command):
    await store.memory_row(session, lock=True)
    row = await load(session, command.task_id)
    value, event = row.value, command.task_event
    if value.get("profile_binding_id") != str(command.profile_binding_id):
        raise ToolDenied("PROFILE_NOT_SELECTED")
    if command.expected_task_version != value["version"]:
        raise ToolDenied("extension_task_revision_conflict")
    if event in {"recover", "recovered", "worker_restart"} and value["state"] == "FILLING":
        # A lost worker cannot attest which writes completed. Retain uncertainty.
        value = {**value, "verified_receipts": [*value["verified_receipts"], {
            "plan_id": value["plan_id"], "authorization_id": value["authorization_id"],
            "packet_revision": value["packet_revision"], "profile_version": value["profile_version"],
            "verification_method": "unknown", "state": "manual_required", "results": [],
            "reason": event, "recorded_at": now(), "submitted": False,
        }][-50:]}
        row.value = value
    if event in {"recover", "recovered"}:
        if not command.browser_session_id or value["state"] in TERMINAL:
            raise ToolDenied("extension_task_terminal")
        reason = value["reason"] if value.get("state") == "PAUSED" and value.get("reason") in {"owner_pause", "global_stop"} else "browser_restart_fresh_inspection_required"
        return move(session, row, "PAUSED", reason,
            browser_session_id=str(command.browser_session_id), tab_id=None, tab_active=False,
            browser_connection="disconnected", plan_id=None, authorization_id=None, network_guard_active=False)
    if str(command.browser_session_id) != value["browser_session_id"]:
        raise ToolDenied("extension_tab_binding_mismatch")
    if event == "guard_released":
        if command.tab_id != value["tab_id"] or command.tab_id is None:
            raise ToolDenied("extension_tab_binding_mismatch")
        reason = value["reason"] if value.get("state") == "PAUSED" and value.get("reason") in {"owner_pause", "global_stop"} else "owner_returned_browser_control"
        return move(session, row, value["state"] if value["state"] in TERMINAL else "PAUSED", reason,
            network_guard_active=False, plan_id=None, authorization_id=None)
    if value["state"] in TERMINAL:
        raise ToolDenied("extension_task_terminal")
    if event == "bind":
        if command.tab_id is None:
            raise ToolDenied("extension_tab_required")
        await fresh(session, settings, value)
        if value.get("state") == "PAUSED" and value.get("reason") in {"owner_pause", "global_stop"}:
            raise ToolDenied("extension_task_paused_or_cancelled")
        if value["tab_id"] is not None and value["tab_id"] != command.tab_id:
            raise ToolDenied("extension_tab_already_bound")
        if command.observed_url and command.observed_url != value["target_url"]:
            raise ToolDenied("extension_destination_mismatch")
        await unclaimed(session, command.task_id, command.browser_session_id, command.tab_id)
        return move(session, row, "PACKET_READY", "tab_bound_fresh_inspection_required",
            tab_id=command.tab_id, window_id=command.window_id, current_url=value["target_url"], tab_active=True,
            browser_connection="connected", plan_id=None, authorization_id=None)
    if event == "worker_restart":
        reason = value["reason"] if value.get("state") == "PAUSED" and value.get("reason") in {"owner_pause", "global_stop"} else "worker_restart_fresh_inspection_required"
        return move(session, row, "PAUSED", reason,
            plan_id=None, authorization_id=None, browser_connection="paused")
    if event in {"pause", "paused", "cancel", "resume"}:
        return await control(session, settings, row, event.replace("paused", "pause"), value["version"])
    if command.tab_id != value["tab_id"] or command.tab_id is None:
        raise ToolDenied("extension_tab_binding_mismatch")
    if event == "guard_installed":
        return move(session, row, value["state"], "tab_network_guard_installed", network_guard_active=True)
    if event == "inspection_prepared":
        if value["state"] == "PAUSED":
            raise ToolDenied("extension_task_paused_or_cancelled")
        from backend.app.browser.service import FormService
        _, plan = await FormService(session, settings).load(command.plan_id)
        return await attach_plan(session, settings, row, plan)
    if event in {"navigation", "refresh", "refreshed", "focus_lost", "active_tab_changed", "tab_closed", "network_timeout"}:
        destination = permitted_navigation(value, command.observed_url or value["current_url"])
        reason = (
            value["reason"]
            if value.get("state") == "PAUSED" and (
                value.get("reason") in {"owner_pause", "global_stop"}
                or event in {"focus_lost", "active_tab_changed"})
            else ("unexpected_navigation" if event == "navigation" and destination is None else event)
        )
        return move(session, row, "FAILED_RETRYABLE" if event == "network_timeout" else "PAUSED", reason,
            current_url=destination or value["current_url"], tab_id=None if event == "tab_closed" else value["tab_id"],
            tab_active=False, browser_connection="disconnected" if event == "tab_closed" else "paused",
            plan_id=None, authorization_id=None, network_guard_active=False if event == "tab_closed" else value.get("network_guard_active", False))
    if event == "fill_started":
        if value["state"] == "FILLING" and str(command.plan_id) == value["plan_id"]:
            return value
        if value["state"] != "FILL_AUTHORIZED" or str(command.plan_id) != value["plan_id"]:
            raise ToolDenied("extension_task_not_authorized")
        return move(session, row, "FILLING", "approved_fill_started")
    if event == "fill_finished":
        raise ToolDenied("verified_fill_receipt_required")
    raise ToolDenied("extension_task_event_required")


async def control(session, settings, row, action, expected_version):
    await store.memory_row(session, lock=True)
    if expected_version != row.value["version"]:
        raise ToolDenied("extension_task_revision_conflict")
    if row.value["state"] in TERMINAL:
        raise ToolDenied("extension_task_terminal")
    state = "PAUSED"
    if action == "resume":
        await fresh(session, settings, row.value)
        state = "PACKET_READY" if row.value["tab_id"] is not None else "PAUSED"
    elif action == "cancel":
        state = "FAILED_FINAL"
    return move(session, row, state, "owner_" + action,
        browser_connection="connected" if action == "resume" and row.value["tab_id"] is not None else ("disconnected" if row.value["tab_id"] is None else "paused"),
        plan_id=None, authorization_id=None)


async def dispatch_task(session, settings, actor, command):
    from backend.app.local_agent.contracts import Result
    from backend.app.services.applications.base import ApplicationError
    if actor.channel != "chrome" or actor.identity != settings.CHROME_EXTENSION_ID:
        return Result(request_id=command.request_id, ok=False, capability="extension_task", error_code="extension_identity_required")
    try:
        from backend.app.browser.chrome_profiles import require_profile
        await require_profile(session, command)
        async with session.begin_nested():
            key = f"extension_request:{actor.identity}:{command.request_id}"
            previous = await session.get(AgentOperation, key)
            if previous:
                raise ToolDenied("form_request_already_consumed")
            if command.command == "open_application_task":
                if not command.application_id:
                    raise ToolDenied("application_id_required")
                row = await create(session, settings, command.application_id, command.browser_session_id, command.tab_id,
                    command.profile_binding_id, command.window_id, command.expected_task_version)
                data = {"task": row.value, "submitted": False}
            elif command.command == "get_application_task":
                row = await load(session, command.task_id)
                if row.value.get("profile_binding_id") != str(command.profile_binding_id):
                    raise ToolDenied("PROFILE_NOT_SELECTED")
                if command.expected_task_version is not None:
                    row = await bound(session, command, allow_background_inspection=True)
                    await fresh(session, settings, row.value)
                if row.value["state"] == "FILLING":
                    try:
                        await fresh(session, settings, row.value)
                    except ToolDenied:
                        move(session, row, "PAUSED", "candidate_or_packet_changed_during_fill",
                            plan_id=None, authorization_id=None, browser_connection="paused")
                data = {"task": row.value, "submitted": False}
            elif command.command == "update_application_task":
                data = {"task": await update(session, settings, command), "submitted": False}
            else:
                row = await bound(session, command)
                data = await ask_questions(session, settings, row)
            if command.command != "get_application_task":
                session.add(AgentOperation(key=key, actor=f"chrome:{actor.identity}", command=command.command,
                    payload_hash=hashlib.sha256(command.model_dump_json().encode()).hexdigest(),
                    result={"task_id": data["task"]["id"], "submitted": False}))
                await session.flush()
            return Result(request_id=command.request_id, ok=True, capability="extension_task", data=data)
    except (ValueError, ApplicationError) as exc:
        code = str(exc) if isinstance(exc, ToolDenied) else "extension_task_context_rejected"
        return Result(request_id=command.request_id, ok=False, capability="extension_task", error_code=code)


def field_question(field):
    """Semantic context is part of a question; repeated dates cannot alias."""
    question = field.group_label or field.label
    parts = [value for value in (field.page_step, field.section, question) if value]
    return ": ".join(dict.fromkeys(parts))


async def ask_questions(session, settings, row):
    """Explicit Ask gesture only queues owner prompts; the bot worker delivers them."""
    from backend.app.browser.service import FormService
    from backend.app.execution import questions
    from backend.app.models.application_packet import ApplicationPacketField
    from backend.app.schemas.applications import QuestionInput, QuestionsAdd
    from backend.app.services.applications.service import ApplicationPacketService

    if row.value["state"] in TERMINAL | {"PAUSED", "FILL_AUTHORIZED", "FILLING"}:
        raise ToolDenied("extension_task_not_waiting_for_answers")
    packet = await fresh(session, settings, row.value)
    if not row.value["plan_id"]:
        raise ToolDenied("fresh_form_inspection_required")
    service = FormService(session, settings)
    _, plan = await service.load(UUID(row.value["plan_id"]))
    await service.fresh(plan)
    unresolved = {a.field_id for a in plan.actions if a.needs_input}
    field_ids = []
    for form_field in plan.inspection.fields:
        if form_field.field_id not in unresolved or form_field.kind in {"file", "checkbox", "radio"} or len(form_field.label) >= 160 or len(form_field.group_label or "") >= 160:
            continue
        question_text = field_question(form_field)
        try:
            questions.permitted(question_text)
        except ToolDenied:
            continue
        # Unknown repeated labels need an unambiguous, stable entry identity first.
        if sum(field_question(other) == question_text for other in plan.inspection.fields) > 1:
            continue
        matches = [f for f in packet.fields if f.question == question_text
                   and f.provenance.form_semantic_key in {None, form_field.semantic_key}]
        if len(matches) > 1:
            continue
        field = matches[0] if matches else None
        if field and field.human_answer and field.review_status == "reviewed":
            continue
        if field is None:
            packet = await ApplicationPacketService(session).add_questions(packet.id, QuestionsAdd(
                expected_revision=packet.revision,
                questions=[QuestionInput(question=question_text,
                    field_type="multiple_choice" if form_field.options and len(form_field.options) <= 50 else "text",
                    options=form_field.options if len(form_field.options) <= 50 else [],
                    required=form_field.required, max_characters=form_field.max_length)],
            ))
            field = next(f for f in packet.fields if f.question == question_text)
        saved_field = await session.get(ApplicationPacketField, field.id)
        saved_field.provenance = {**saved_field.provenance,
            "form_semantic_key": form_field.semantic_key,
            "form_page_step": form_field.page_step, "form_section": form_field.section}
        field_ids.append(field.id)
    await session.flush()
    packet = await ApplicationPacketService(session).read(packet.id)
    # Reuse the existing durable owner-only question channel, never a new uncorrelated bot.
    intent = await store.packet_question_intent(session, packet) if field_ids else None
    envelopes = []
    for field_id in field_ids:
        envelope = await questions.ask(session, intent["id"], field_id)
        await session.flush()
        saved_field = await session.get(ApplicationPacketField, field_id)
        observed = next((f for f in plan.inspection.fields if field_question(f) == saved_field.question), None)
        question_row = await session.get(OwnerPreference, questions.PREFIX + envelope["id"])
        question_row.value = {**question_row.value, "form_kind": observed.kind if observed else None,
            "form_semantic_key": saved_field.provenance.get("form_semantic_key"),
            "extension_task_id": row.value["id"]}
        envelopes.append(question_row.value)
    # All envelopes are created after the final packet revision so replies cannot strand siblings.
    task = move(session, row, "NEEDS_INPUT", "owner_questions_queued", packet_revision=packet.revision,
        field_answer_revisions={str(f.id): f.answer_revision for f in packet.fields},
        plan_id=None, authorization_id=None)
    return {"task": task, "questions": envelopes, "submitted": False}


async def answer_saved(session, question, updated_packet, waiting):
    """Reply processing advances only this packet's task; it grants no fill rights."""
    identity = question.get("extension_task_id")
    if not identity:
        return
    row = await load(session, identity)
    if row.value["application_id"] != str(updated_packet.id):
        raise ToolDenied("extension_answer_context_mismatch")
    state = row.value["state"]
    if state not in TERMINAL | {"PAUSED"}:
        state = "NEEDS_INPUT" if waiting else "PACKET_READY"
    move(session, row, state, "owner_answer_saved_fresh_inspection_required",
        packet_revision=updated_packet.revision,
        field_answer_revisions={str(f.id): f.answer_revision for f in updated_packet.fields},
        plan_id=None, authorization_id=None,
        counts={**row.value["counts"], "missing": max(0, row.value["counts"]["missing"] - 1)})
