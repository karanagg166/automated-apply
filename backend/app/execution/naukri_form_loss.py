"""Quarantine a genuinely lost original form without replaying any browser write."""

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import naukri_identity, store


async def report(session, identity, binding, settings, *, source="trusted_extension_original_tab_missing"):
    await store.memory_row(session, lock=True)
    row = await queue.load(session, identity)
    value = dict(row.value)
    original = value.get("form_binding") or {}
    if (not value.get("admitted_actions") or not original
            or any(original.get(k) != binding.get(k) for k in (
                "profile_binding_id", "browser_session_id", "window_id", "tab_id"))):
        raise ToolDenied("original_form_loss_binding_required")
    if source not in {"trusted_extension_original_tab_missing", "owner_operator_exact_original_tab_missing", "authenticated_browser_session_replaced", "authenticated_browser_window_replaced"}:
        raise ToolDenied("form_loss_source_invalid")
    # A server-authenticated browser restart fences its own old documents even
    # if platform approval was revoked. It grants no provider access or replay.
    if source not in {"authenticated_browser_session_replaced", "authenticated_browser_window_replaced"}:
        account = await naukri_identity.require(session, value["candidate_profile_id"])
        if (account["revision"] != value["account_binding_revision"]
                or account["account_sha256"] != value["account_sha256"]
                or account["profile_binding_id"] != original["profile_binding_id"]):
            raise ToolDenied("form_loss_account_binding_changed")
    if value["stage"] == "SUBMITTED_CONFIRMED" or value.get("form_loss_observation"):
        return False
    if not value.get("form_pending"):
        raise ToolDenied("pending_original_form_required")
    now = (await instant(session)).isoformat()
    value.update(
        stage="SUBMISSION_UNKNOWN", status="unknown", operation="reconcile_application",
        reason=("original_questionnaire_context_replaced_reconcile_only"
                if source in {"authenticated_browser_session_replaced", "authenticated_browser_window_replaced"}
                else "original_questionnaire_tab_unavailable_reconcile_only"),
        revision=value["revision"] + 1, updated_at=now, lease_token=None, lease_until=None,
        form_loss_observation={"at": now, "source": source,
                               "original_tab_id": original["tab_id"], "replay_authorized": False},
    )
    row.value = value
    questions = select(OwnerPreference).where(
        OwnerPreference.key.startswith("exec_q:"),
        OwnerPreference.value["queue_work_id"].as_string() == str(identity),
        OwnerPreference.value["state"].as_string().in_(["pending", "sent", "delivery_unknown"]),
    ).execution_options(populate_existing=True)
    for question in (await session.scalars(questions)).all():
        question.value = {**question.value, "state": "closed_form_unavailable", "closed_at": now,
                          "reuse_approved": False}
    await queue.event(session, value, "original_form_lost_reconcile_only_no_replay")
    from backend.app.execution.naukri_submission import notify_unknown

    await notify_unknown(session, value, settings)
    return True


async def session_replaced(session, profile_binding_id, previous_session_id, settings, *, previous_window_id=None, window_only=False):
    """A new authenticated browser session cannot resume the old document."""
    rows = select(OwnerPreference).where(
        OwnerPreference.key.startswith(queue.PREFIX),
        OwnerPreference.value["form_pending"].as_boolean().is_(True),
        OwnerPreference.value["form_binding"]["profile_binding_id"].as_string() == str(profile_binding_id),
        OwnerPreference.value["form_binding"]["browser_session_id"].as_string() == str(previous_session_id),
        OwnerPreference.value["stage"].as_string().not_in(queue.TERMINAL),
    ).execution_options(populate_existing=True)
    if previous_window_id is not None:
        rows = rows.where(OwnerPreference.value["form_binding"]["window_id"].as_integer() == previous_window_id)
    for row in (await session.scalars(rows)).all():
        if not row.value.get("form_loss_observation"):
            await report(session, row.value["id"], row.value["form_binding"], settings,
                         source="authenticated_browser_window_replaced" if window_only else "authenticated_browser_session_replaced")
