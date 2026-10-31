"""Versioned canonical/portal comparison. Unknown values never clear a portal.

Only a separately approved supported field can be written. Audit records retain
hash references, not contact details, compensation, resumes or raw page content.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import Field

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.contracts import Contract
from backend.app.execution.recurring import context

FieldName = Literal["full_name", "email", "phone", "summary", "skills", "experience", "education", "projects", "location", "preferences", "notice_period", "expected_compensation", "resume", "github", "portfolio", "linkedin", "headline", "professional_title"]
FIELDS = ("full_name", "email", "phone", "summary", "skills", "experience", "education", "projects", "location", "preferences", "notice_period", "expected_compensation", "resume", "github", "portfolio", "linkedin", "headline", "professional_title")
SUPPORTED_WRITES = {"summary"}
POLICY = "naukri_profile_sync_policy"
WORK = "apply_profile_sync:naukri"
RECORD = "nau_sync:"
OPERATIONS = {"inspect_profile_sync", "sync_profile"}


class SyncPolicy(Contract):
    enabled: bool = False
    auto_profile_sync: bool = False
    profile_version: int | None = Field(None, ge=1)
    approved_fields: list[FieldName] = Field(default_factory=list, max_length=18)
    interval_seconds: int = Field(3600, ge=300, le=86400)


class SyncPolicyUpdate(Contract):
    expected_revision: int = Field(ge=0)
    policy: SyncPolicy


def reference(value):
    if value is None or value == "" or value == [] or value == {}:
        return None
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def compare(canonical, observed, approved_fields=()):
    result = []
    for name in FIELDS:
        desired, actual = reference(canonical.get(name)), reference(observed.get(name))
        if name not in observed:
            state = "UNSUPPORTED"
        elif not desired and actual:
            state = "MISSING_FROM_DATABASE"
        elif desired == actual:
            state = "MATCHED"
        elif desired and not actual:
            state = "MISSING_FROM_PLATFORM"
        else:
            state = "OUTDATED" if name in approved_fields else "CONFLICT"
        result.append({"field": name, "state": state, "previous_reference": actual,
                       "new_reference": desired,
                       "update_supported": name in SUPPORTED_WRITES,
                       "may_update": bool(desired and name in approved_fields and name in SUPPORTED_WRITES
                                          and state in {"OUTDATED", "MISSING_FROM_PLATFORM"})})
    return result


def canonical(profile, resume):
    preferences = profile.preferences or {}
    return {
        "full_name": profile.full_name, "email": profile.email, "phone": profile.phone,
        "summary": profile.summary, "skills": profile.verified_skills,
        "experience": profile.verified_roles, "education": profile.education, "projects": profile.projects,
        "location": preferences.get("current_location"),
        "preferences": {k: preferences[k] for k in ("preferred_locations", "remote_preference") if k in preferences},
        "notice_period": preferences.get("notice_period_days"),
        # A job-search salary floor is never a personal salary/CTC fact.
        "expected_compensation": preferences.get("expected_compensation"),
        "resume": resume.resource_version if resume else None,
        "github": profile.github_url, "portfolio": profile.portfolio_url, "linkedin": profile.linkedin_url,
        # Target-role preferences and past employment are not an approved current
        # title or headline. Keep these unknown until such facts are saved.
        "headline": None, "professional_title": None,
    }


async def configuration(session):
    row = await session.get(OwnerPreference, POLICY, populate_existing=True)
    return dict(row.value) if row else {"revision": 0, "policy": SyncPolicy().model_dump(mode="json")}


async def configure(session, data):
    await queue.store.memory_row(session, lock=True)
    current = await configuration(session)
    if data.expected_revision != current["revision"]:
        raise ToolDenied("profile_sync_revision_conflict")
    profile, confirmed, _ = await context(session)
    if data.policy.enabled and (not confirmed or data.policy.profile_version != profile.version):
        raise ToolDenied("current_confirmed_profile_version_required")
    work = await session.get(OwnerPreference, WORK, populate_existing=True)
    if work:
        value = work.value
        if value.get("status") == "executing" and value.get("operation") == "sync_profile":
            raise ToolDenied("profile_sync_in_progress_reconcile_before_change")
        work.value = {**value, "status": "idle", "lease_until": None, "lease_token": None,
                      "revision": value["revision"] + 1, "next_at": None}
    result = {"revision": current["revision"] + 1, "policy": data.policy.model_dump(mode="json")}
    await queue.put(session, POLICY, result)
    return result


async def work(session, config, binding):
    settings = await configuration(session)
    policy = SyncPolicy.model_validate(settings["policy"])
    if not policy.enabled:
        return None
    profile, confirmed, resume = await context(session)
    if not confirmed or policy.profile_version != profile.version:
        return None
    row = await session.get(OwnerPreference, WORK, populate_existing=True)
    old = dict(row.value) if row else {}
    now = await instant(session)
    if old.get("lease_until") and datetime.fromisoformat(old["lease_until"]) > now:
        return None
    if old.get("next_at") and datetime.fromisoformat(old["next_at"]) > now:
        return None
    from backend.app.execution.naukri_identity import require

    try:
        account = await require(session, profile.id, binding["profile_binding_id"])
    except ToolDenied:
        return None
    value = {"id": str(uuid5(NAMESPACE_URL, WORK)), "revision": old.get("revision", 0) + 1,
             "policy_revision": config["revision"], "sync_policy_revision": settings["revision"],
             "profile_version": profile.version, "binding": binding, "status": "leased",
             "operation": "inspect_profile_sync", "url": "https://www.naukri.com/mnjuser/profile",
             "requisition": None, "lease_token": str(uuid4()), "lease_until": (now + timedelta(seconds=180)).isoformat(),
             "candidate_profile_id": str(profile.id), "account_binding_revision": account["revision"],
             "account_sha256": account["account_sha256"],
             "next_at": (now + timedelta(seconds=policy.interval_seconds)).isoformat(),
             "sync_attempt": old.get("sync_attempt"), "last_record": old.get("last_record")}
    await queue.put(session, WORK, value)
    return value


async def validate(session, value):
    from backend.app.execution.naukri_identity import check_work

    await check_work(session, value)
    settings = await configuration(session)
    policy = SyncPolicy.model_validate(settings["policy"])
    profile, confirmed, resume = await context(session)
    if (not policy.enabled or not confirmed or profile.version != value["profile_version"]
            or policy.profile_version != profile.version or value["sync_policy_revision"] != settings["revision"]):
        raise ToolDenied("profile_sync_context_changed")
    return profile, resume, policy


async def admit(session, value):
    profile, resume, policy = await validate(session, value)
    if value["operation"] == "sync_profile":
        if not policy.auto_profile_sync or "summary" not in policy.approved_fields or value.get("sync_attempt"):
            raise ToolDenied("profile_sync_write_scope_or_reconciliation_required")
        if reference(profile.summary) != value.get("new_summary_reference") or not profile.summary:
            raise ToolDenied("profile_sync_canonical_value_changed")
        value["sync_attempt"] = {"id": str(uuid4()), "at": (await instant(session)).isoformat(),
                                 "document_id": value["document_id"],
                                 "previous_reference": value["previous_summary_reference"],
                                 "new_reference": value["new_summary_reference"], "outcome": "UNKNOWN"}
        value["approved_summary"] = profile.summary
        value["permit_expires_at"] = ((await instant(session)) + timedelta(seconds=2)).isoformat()
        identity = str(uuid4())
        await queue.put(session, RECORD + identity, {
            "id": identity, "profile_version": profile.version, "sync_policy_revision": value["sync_policy_revision"],
            "observed_at": (await instant(session)).isoformat(), "decisions": [],
            "outcome": "SYNC_ADMITTED_OUTCOME_UNKNOWN", "attempt": value["sync_attempt"],
        })
        value["last_record"] = identity
    value.update(status="executing", revision=value["revision"] + 1)
    return value


async def receive(session, value, report):
    profile, resume, policy = await validate(session, value)
    if report.kind in {"needs_input", "failed"}:
        value.update(status="idle", last_error=report.reason or "profile_sync_observation_failed")
        value.pop("approved_summary", None)
        if value.get("sync_attempt"):
            identity = str(uuid4())
            await queue.put(session, RECORD + identity, {
                "id": identity, "profile_version": profile.version, "sync_policy_revision": value["sync_policy_revision"],
                "observed_at": (await instant(session)).isoformat(), "decisions": [],
                "outcome": "SYNC_UNCONFIRMED_NO_RETRY", "attempt": value["sync_attempt"],
                "failure_code": value["last_error"],
            })
            value["last_record"] = identity
        return False
    observation = report.execution
    if (report.kind != "execution_observation" or not observation
            or observation.account_sha256 != value["account_sha256"]
            or str(report.observed_url) != value["url"]):
        raise ToolDenied("profile_sync_account_or_document_changed")
    if value["operation"] == "sync_profile":
        if observation.state != "PROFILE_SAVE_ATTEMPTED":
            raise ToolDenied("profile_sync_save_observation_required")
        value.pop("approved_summary", None)
        value.update(operation="inspect_profile_sync", status="leased", verifying_save=True)
        return True
    if observation.state != "PROFILE_OBSERVED":
        raise ToolDenied("profile_sync_observation_required")
    decisions = compare(canonical(profile, resume), observation.profile_fields, policy.approved_fields)
    now = await instant(session)
    identity = str(uuid4())
    record = {"id": identity, "profile_version": profile.version, "sync_policy_revision": value["sync_policy_revision"],
              "observed_at": now.isoformat(), "decisions": decisions,
              "evidence_sha256": observation.evidence_sha256,
              "outcome": "COMPARED", "attempt": value.get("sync_attempt")}
    summary = next(d for d in decisions if d["field"] == "summary")
    if value.get("sync_attempt"):
        if value["sync_attempt"].get("document_id") == observation.document_id:
            raise ToolDenied("independent_profile_reload_required")
        matched = summary["state"] == "MATCHED" and summary["new_reference"] == value["sync_attempt"]["new_reference"]
        record["outcome"] = "SYNC_VERIFIED" if matched else "SYNC_UNCONFIRMED_NO_RETRY"
        value["sync_attempt"] = {**value["sync_attempt"], "outcome": record["outcome"]}
        # Reconciliation can complete a failed/lost save, but never replay it.
    value.update(last_record=identity, last_error=None, status="idle")
    await queue.put(session, RECORD + identity, record)
    if policy.auto_profile_sync and summary["may_update"] and not value.get("sync_attempt"):
        value.update(operation="sync_profile", status="leased", document_id=observation.document_id,
                     previous_summary_reference=summary["previous_reference"], new_summary_reference=summary["new_reference"])
        return True
    return False


async def status(session):
    profile, confirmed, _ = await context(session)
    work_row = await session.get(OwnerPreference, WORK, populate_existing=True)
    record = await session.get(OwnerPreference, RECORD + work_row.value["last_record"]) if work_row and work_row.value.get("last_record") else None
    return {"configuration": await configuration(session), "latest": record.value if record else None,
            "current_profile_version": profile.version if profile else None, "profile_confirmed": confirmed,
            "last_error": work_row.value.get("last_error") if work_row else None,
            "supported_updates": sorted(SUPPORTED_WRITES), "live_accepted": False}
