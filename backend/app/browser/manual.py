"""Native-origin-authenticated manual mode. The popup supplies the user gesture."""

import hashlib

from backend.app.agent.tools import ToolDenied
from backend.app.browser.service import FormService
from backend.app.local_agent.contracts import Result
from backend.app.local_agent.models import AgentOperation


async def dispatch_form(session, settings, actor, command):
    key = f"manual_form:{actor.identity}:{command.request_id}"
    previous = await session.get(AgentOperation, key)
    digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    if previous:
        if previous.payload_hash != digest:
            raise ToolDenied("native_request_conflict")
        # Never replay executable values after authorization was consumed.
        return Result(
            request_id=command.request_id,
            ok=False,
            capability="form_fill",
            error_code="form_request_already_consumed",
        )
    try:
        if (
            actor.channel != "chrome"
            or actor.identity != settings.CHROME_EXTENSION_ID
            or not settings.BROWSER_FILL_ENABLED
        ):
            raise ToolDenied("manual_form_not_authorized")
        service = FormService(session, settings)
        if command.command == "prepare_form_answers":
            if not command.inspection:
                raise ToolDenied("application_and_inspection_required")
            plan = await service.prepare_current_form(command.inspection, command.title)
            data = {"plan": plan.model_dump(mode="json"), "submitted": False}
        elif command.command == "inspect_form":
            if not command.application_id or not command.inspection:
                raise ToolDenied("application_and_inspection_required")
            plan = await service.inspect(
                command.application_id, command.inspection, "manual_extension"
            )
            data = {"plan": plan.model_dump(mode="json"), "submitted": False}
        elif command.command == "authorize_form":
            if not command.plan_id:
                raise ToolDenied("plan_required")
            await service.review(command.plan_id, command.field_ids)
            plan, _ = await service.consume(command.plan_id, "manual_extension")
            data = {"plan": plan.model_dump(mode="json"), "submitted": False}
        else:
            if not command.receipt:
                raise ToolDenied("receipt_required")
            data = await service.receipt(command.receipt)
        result = Result(
            request_id=command.request_id, ok=True, capability="form_fill", data=data
        )
        # Receipt contains identifiers/status only; preview values are private plan data.
        session.add(
            AgentOperation(
                key=key,
                actor=f"chrome:{actor.identity}",
                command=command.command,
                payload_hash=digest,
                result={"status": "processed", "submitted": False},
            )
        )
        await session.flush()
        return result
    except ValueError as exc:
        allowed = {
            "manual_form_not_authorized", "profile_review_required",
            "unsupported_application_form", "platform_fill_policy_denied",
            "application_not_eligible", "fill_plan_stale",
        }
        return Result(
            request_id=command.request_id,
            ok=False,
            capability="form_fill",
            error_code=str(exc) if isinstance(exc, ToolDenied) and str(exc) in allowed else "form_permission_or_context_rejected",
        )
