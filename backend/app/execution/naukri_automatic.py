"""Recurring AUTO requires a genuinely confirmed prior worker submission.

Historical/operator observations and reconciliation without an admitted Apply
never establish the first-new-application prerequisite. Other current identity,
profile, PDF, eligibility and write guards still run for every application.
"""

from sqlalchemy import literal, select
from sqlalchemy.orm import aliased

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution.naukri_identity import require as require_account
from backend.app.execution.naukri_receipts import worker_recorded


async def require_first_receipt(session):
    account = await require_account(session)
    now = await instant(session)
    receipt_row, work_row = aliased(OwnerPreference), aliased(OwnerPreference)
    # Stream newest proofs in small batches, stopping at the first valid one.
    # Do not reload the growing receipt/history ledger on each AUTO action.
    query = select(receipt_row.key, receipt_row.value, work_row.value).join(
        work_row, work_row.key == literal("apply_work:") + receipt_row.value["queue_id"].as_string(),
    ).where(
        receipt_row.key.startswith("naukri_worker_receipt:"),
        receipt_row.value["account_sha256"].as_string() == account["account_sha256"],
        receipt_row.value["worker_dispatched"].as_boolean().is_(True),
        work_row.value["stage"].as_string() == "SUBMITTED_CONFIRMED",
    ).order_by(receipt_row.created_at.desc(), receipt_row.key).execution_options(yield_per=10)
    result = await session.stream(query)
    try:
        async for key, receipt, value in result:
            actions = value.get("admitted_actions")
            if (worker_recorded(key, receipt, now) and receipt.get("worker_dispatched") is True
                    and receipt["account_sha256"] == account["account_sha256"]
                    and value.get("id") == receipt.get("queue_id")
                    and value.get("platform") == "naukri"
                    and value.get("requisition") == receipt["requisition"]
                    and value.get("candidate_profile_id") == account["candidate_profile_id"]
                    and value.get("account_sha256") == account["account_sha256"]
                    and value.get("account_binding_revision") == account["revision"]
                    and value.get("stage") == "SUBMITTED_CONFIRMED"
                    and value.get("submission_mode") == "recurring_worker_ui"
                    and isinstance(actions, list)
                    and any(str(action.get("fingerprint", "")).startswith("apply:")
                            for action in actions if isinstance(action, dict))):
                return receipt["requisition"]
    finally:
        await result.close()
    raise ToolDenied("automatic_first_verified_worker_receipt_required")


async def require_policy(session, policy):
    setting = policy.platforms["naukri"]
    if setting.enabled and setting.mode == "AUTOMATIC" and setting.owner_submission_authorized:
        await require_first_receipt(session)
