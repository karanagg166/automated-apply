"""Native-origin-authenticated manual mode. The popup supplies the user gesture."""

import hashlib
from uuid import UUID

from backend.app.agent.tools import ToolDenied
from backend.app.browser import extension_tasks as tasks
from backend.app.browser.service import FormService
from backend.app.local_agent.contracts import Result
from backend.app.local_agent.models import AgentOperation


async def dispatch_form(session, settings, actor, command):
    from backend.app.execution.store import memory_row

    # The same durable owner lock precedes packet/plan locks in every Chrome path.
    await memory_row(session, lock=True)
    key = f"manual_form:{actor.identity}:{command.request_id}"
    previous = await session.get(AgentOperation, key)
    digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    if previous:
        return Result(request_id=command.request_id, ok=False, capability="form_fill",
            error_code="native_request_conflict" if previous.payload_hash != digest else "form_request_already_consumed")
    try:
        async with session.begin_nested():
            if (
                actor.channel != "chrome"
                or actor.identity != settings.CHROME_EXTENSION_ID
                or (command.command in {"authorize_form", "record_form_fill"}
                    and not settings.BROWSER_FILL_ENABLED)
            ):
                raise ToolDenied("manual_form_not_authorized")
            service = FormService(session, settings)
            task = None
            if command.task_id and command.command != "record_form_fill":
                task = await tasks.bound(session, command, require_plan=command.command == "authorize_form")
            if command.command == "prepare_form_answers":
                if not command.inspection:
                    raise ToolDenied("application_and_inspection_required")
                if task:
                    raise ToolDenied("bound_task_requires_saved_application_inspection")
                plan = await service.prepare_current_form(command.inspection, command.title)
                data = {"plan": plan.model_dump(mode="json"), "submitted": False}
            elif command.command == "inspect_form":
                if not command.application_id or not command.inspection:
                    raise ToolDenied("application_and_inspection_required")
                if task and task.value["application_id"] != str(command.application_id):
                    raise ToolDenied("extension_task_plan_mismatch")
                plan = await service.inspect(command.application_id, command.inspection, "manual_extension")
                if task:
                    await tasks.attach_plan(session, settings, task, plan)
                data = {"plan": plan.model_dump(mode="json"), "submitted": False}
            elif command.command == "authorize_form":
                if not command.plan_id:
                    raise ToolDenied("plan_required")
                _, current_plan = await service.load(command.plan_id)
                if current_plan.extension_task_id and (not task or current_plan.extension_task_id != UUID(task.value["id"])):
                    raise ToolDenied("extension_task_required")
                if task:
                    await tasks.fresh(session, settings, task.value)
                    if task.value["state"] not in {"FORM_INSPECTED", "NEEDS_INPUT", "ANSWERS_REVIEWED"}:
                        raise ToolDenied("extension_task_not_ready_for_review")
                    if task.value["challenge_state"] not in tasks.CHALLENGE_SAFE:
                        raise ToolDenied("challenge_fresh_review_required")
                await service.review(command.plan_id, command.field_ids)
                plan, _ = await service.consume(command.plan_id, "manual_extension")
                if task:
                    plan.extension_authorization_id = command.request_id
                    saved, _ = await service.load(plan.id)
                    saved.value = plan.model_dump(mode="json")
                    tasks.move(session, task, "ANSWERS_REVIEWED", "exact_fields_reviewed")
                    tasks.move(session, task, "FILL_AUTHORIZED", "single_use_authorization",
                        authorization_id=str(command.request_id))
                    tasks.move(session, task, "FILLING", "approved_fill_pending_receipt")
                data = {"plan": plan.model_dump(mode="json"), "submitted": False}
            else:
                if not command.receipt:
                    raise ToolDenied("receipt_required")
                _, plan = await service.load(command.receipt.plan_id)
                if plan.extension_task_id:
                    if command.task_id != plan.extension_task_id:
                        raise ToolDenied("extension_task_required")
                    task = await tasks.load(session, command.task_id)
                    if (str(command.browser_session_id) != task.value["browser_session_id"]
                        or command.tab_id is None or command.tab_id != task.value["tab_id"]):
                        raise ToolDenied("extension_tab_binding_mismatch")
                    # Receipts from an interrupted fill are audit evidence only. They cannot
                    # revive a paused/cancelled task or authorize any further write.
                    if task.value["state"] == "FILLING":
                        if command.expected_task_version != task.value["version"] or task.value["plan_id"] != str(plan.id):
                            raise ToolDenied("extension_task_revision_conflict")
                data = await service.receipt(command.receipt)
                if task and data["status"] != "already_recorded":
                    verified = command.receipt.verification_method == "retained_after_blur"
                    successful = [r for r in command.receipt.results if r.status == "filled"] if verified else []
                    receipts = [*task.value["verified_receipts"], {
                        "plan_id": str(plan.id), "authorization_id": str(plan.extension_authorization_id) if plan.extension_authorization_id else None,
                        "document_id": plan.inspection.document_id, "packet_revision": plan.packet_revision,
                        "profile_version": plan.actions[0].candidate_version if plan.actions else task.value["profile_version"],
                        "results": [r.model_dump() for r in command.receipt.results],
                        "verification_method": command.receipt.verification_method,
                        "state": data["status"], "recorded_at": tasks.now(), "submitted": False,
                    }][-50:]
                    counts = {**task.value["counts"], "completed": len(successful),
                        "validation_errors": sum(r.status == "validation_error" for r in command.receipt.results)}
                    next_state = task.value["state"]
                    if next_state == "FILLING":
                        next_state = "FILLED_VERIFIED" if verified and successful and data["status"] == "form_filled" else "NEEDS_INPUT"
                        if verified and data["status"] == "form_filled" and not plan.inspection.has_next:
                            next_state = "READY_FOR_SUBMISSION"
                    tasks.move(session, task, next_state, "fill_receipt_saved" if verified else "fill_unverified_manual_required",
                        verified_receipts=receipts, counts=counts)
            if task:
                data["task"] = task.value
            result = Result(request_id=command.request_id, ok=True, capability="form_fill", data=data)
            # No answer values, resume bytes or raw employer content in the protocol audit.
            session.add(AgentOperation(key=key, actor=f"chrome:{actor.identity}", command=command.command,
                payload_hash=digest, result={"status": "processed", "submitted": False}))
            await session.flush()
            return result
    except ValueError as exc:
        allowed = {
            "manual_form_not_authorized", "profile_review_required",
            "unsupported_application_form", "platform_fill_policy_denied",
            "application_not_eligible", "fill_plan_stale", "extension_task_required",
            "extension_task_revision_conflict", "extension_tab_binding_mismatch",
            "extension_task_plan_mismatch", "extension_task_paused_or_cancelled",
            "extension_task_context_stale", "extension_task_not_ready_for_review",
            "challenge_fresh_review_required", "bound_task_requires_saved_application_inspection",
        }
        return Result(request_id=command.request_id, ok=False, capability="form_fill",
            error_code=str(exc) if isinstance(exc, ToolDenied) and str(exc) in allowed else "form_permission_or_context_rejected")
