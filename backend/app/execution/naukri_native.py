"""Authenticated, profile-bound ordinary UI work with durable write admission.

Every write requires fresh eligibility/CV proof; separate history documents
establish receipts. Only recognized, bound questionnaire controls may continue.
"""

import re
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.browser import chrome_profiles as profiles
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import naukri_questionnaires as questionnaires
from backend.app.execution import naukri_submission as submission
from backend.app.execution import profile_sync, store
from backend.app.execution.queue_contracts import QueuePolicy
from backend.app.local_agent.contracts import Result

SEARCH = "apply_search:naukri"
MAINTENANCE = "naukri_extension_maintenance"
READS = {"inspect_job", "search_jobs"}
TRANSIENT_DISCOVERY_ERRORS = frozenset({
    "backend_not_ready", "backend_timeout", "backend_transaction_rolled_back",
})


def defer_transient_discovery(value, reason, now):
    """Only retry an unattempted listing read, never a provider write or form.

    The original browser tab is closed normally. A new lease/document must pass
    the current account, policy, focus and provider controls on every retry.
    Persist a small backoff/count so restarts cannot create an infinite loop.
    """
    count = value.get("transport_retry_count", 0)
    if (reason not in TRANSIENT_DISCOVERY_ERRORS or value.get("operation") != "inspect_job"
            or value.get("admitted_actions") or value.get("packet_id") or value.get("form_pending")
            or type(count) is not int or not 0 <= count < 3):
        return False
    value.update(stage="FAILED_RETRYABLE", status="queued", reason=reason,
                 transport_retry_count=count + 1,
                 available_at=(now + timedelta(seconds=60 * 2 ** count)).isoformat())
    return True


async def workrow(session, identity):
    sync = await session.get(OwnerPreference, profile_sync.WORK, populate_existing=True)
    if sync and sync.value["id"] == str(identity):
        return sync
    search = await session.get(OwnerPreference, SEARCH, populate_existing=True)
    if search and search.value["id"] == str(identity):
        return search
    return await queue.load(session, identity)


def transport(value):
    # Only the admitted current step's answer is exposed to its bound tab.
    # No browser secrets, source-message references or PDF bytes.
    result = {k: value.get(k) for k in (
        "id", "revision", "lease_token", "lease_until", "operation", "url", "requisition", "binding", "stage", "status",
    )}
    result["form_pending"] = value.get("form_pending", False)
    if value["operation"] in questionnaires.OPERATIONS:
        result.update(target_url=submission.PROFILE_URL if value["operation"] == "refresh_questionnaire_profile" else value["url"],
                      execution=questionnaires.descriptor(value))
    if value["operation"] in submission.OPERATIONS | profile_sync.OPERATIONS:
        result.update(target_url=submission.browser_url(value), execution=submission.descriptor(value))
        if value["operation"] in profile_sync.OPERATIONS:
            result["execution"].update(approved_summary=value.get("approved_summary"),
                                       verify_saved_resume=value.get("verify_saved_resume", False),
                                       previous_summary_reference=value.get("previous_summary_reference"))
            if value.get("sync_field") == "skills":
                result["execution"].update({k: value.get(k) for k in (
                    "sync_field", "sync_phase", "skills_before", "skills_additions", "prepared_skills",
                    "previous_skills_reference", "new_skills_reference",
                )})
    return result


async def search_work(session, config, policy, binding):
    setting = policy.platforms.get("naukri")
    if not setting or "naukri_ui_search" not in setting.sources:
        return None
    now = await instant(session)
    old = await session.get(OwnerPreference, SEARCH, populate_existing=True)
    value = dict(old.value) if old else {}
    if value.get("lease_until") and datetime.fromisoformat(value["lease_until"]) > now:
        return None
    if value.get("next_at") and datetime.fromisoformat(value["next_at"]) > now:
        return None
    from backend.app.execution.recurring import context

    profile, confirmed, _ = await context(session)
    if not confirmed:
        return None
    roles = setting.preferences.roles if setting.preferences_mode == "custom" else (profile.preferences or {}).get("target_titles", [])
    if not roles:
        return None
    # A general Date-sorted search on the genuine portal includes many senior
    # roles. Add an ordinary keyword search for sub-year candidates, preserving
    # every original query and all full-listing eligibility checks. "Fresher"
    # is a discovery hint, never an experience fact or an application exemption.
    if profile.verified_experience_years is not None and 0 <= profile.verified_experience_years < 1:
        roles = list(dict.fromkeys(query for role in roles for query in (
            role if re.search(r"\bfresher\b", role, re.I) else role + " fresher", role,
        )))
    index = value.get("role_index", 0) % len(roles)
    page = 1
    # Actual ordinary search pagination exposes /<role>-jobs-2, ...-3. When
    # page one was exhausted, don't keep revisiting only its same 20 links.
    # Follow at most three pages, one per existing interval, then rotate roles.
    # Reconstruct only the observed same-role path shape, never a provider API
    # or guessed filter/query parameter. Failed/stopped reads reset the sweep.
    previous_index = (index - 1) % len(roles)
    previous_slug = re.sub(r"[^a-z0-9]+", "-", roles[previous_index].lower()).strip("-")
    previous_page = value.get("search_page", 1)
    previous_path = "https://www.naukri.com/" + previous_slug + "-jobs"
    if type(previous_page) is int and previous_page in {2, 3}:
        previous_path += "-" + str(previous_page)
    if (type(previous_page) is int and 1 <= previous_page < 3
            and value.get("status") == "idle" and value.get("last_finished_at")
            and value.get("last_error") is None and value.get("last_cycle_count") == 0
            and value.get("url") == previous_path):
        index, page = previous_index, previous_page + 1
    slug = re.sub(r"[^a-z0-9]+", "-", roles[index].lower()).strip("-")
    if not slug:
        return None
    value = {
        "id": str(uuid5(NAMESPACE_URL, SEARCH)), "revision": value.get("revision", 0) + 1,
        "lease_token": str(uuid4()), "lease_until": (now + timedelta(seconds=180)).isoformat(),
        "operation": "search_jobs", "url": "https://www.naukri.com/" + slug + "-jobs" + ("-" + str(page) if page > 1 else ""),
        "status": "leased", "binding": binding, "policy_revision": config["revision"],
        "role_index": index + 1, "search_page": page, "last_started_at": now.isoformat(),
        "next_at": (now + timedelta(seconds=setting.discovery_interval_seconds)).isoformat(),
        "candidates_found": value.get("candidates_found", 0), "last_error": None,
    }
    await queue.put(session, SEARCH, value)
    return value


async def checked(session, command, binding):
    if not command.work_id or not command.expected_work_revision or not command.work_lease_token:
        raise ToolDenied("queue_lease_fields_required")
    row = await workrow(session, command.work_id)
    value = dict(row.value)
    config, now = await queue.configuration(session), await instant(session)
    setting = QueuePolicy.model_validate(config["policy"]).platforms.get("naukri")
    if (config["state"] != "RUNNING" or not setting or not setting.enabled
            or value["policy_revision"] != config["revision"]
            or value["revision"] != command.expected_work_revision
            or value["lease_token"] != str(command.work_lease_token)
            or value["binding"] != binding or value["status"] not in {"leased", "executing"}
            or not value["lease_until"] or datetime.fromisoformat(value["lease_until"]) <= now):
        raise ToolDenied("queue_lease_lost")
    if value["operation"] not in READS | submission.OPERATIONS | profile_sync.OPERATIONS | questionnaires.OPERATIONS:
        raise ToolDenied("background_submission_executor_pending")
    return row


async def receive_job(session, value, report):
    if not report.observed_url or queue.normalized_url(str(report.observed_url)) != value["url"]:
        raise ToolDenied("queue_document_identity_changed")
    if report.requisition != value["requisition"]:
        raise ToolDenied("queue_requisition_changed")
    if report.stage == "ALREADY_APPLIED":
        value.update(stage="SKIPPED", status="complete", reason="provider_already_applied")
        return
    if report.kind != "job_facts" or not report.job or report.job.requisition != value["requisition"]:
        raise ToolDenied("provider_job_facts_required")
    observed = report.job
    value.update(facts=observed.model_dump(mode="json"), title=observed.title,
                 company=observed.company, location=observed.location)
    policy = QueuePolicy.model_validate((await queue.configuration(session))["policy"])
    reason = queue.listing_exclusion(value["facts"], queue.limits(policy, "naukri"), await instant(session))
    if reason:
        skipped = reason in {"posting_outside_age_limit", "applicant_limit_reached", "applicant_count_unknown_skip"}
        value.update(stage="SKIPPED" if skipped else "NEEDS_INPUT", status="complete" if skipped else "waiting", reason=reason)
        if reason == "applicant_count_requires_review":
            from backend.app.execution.queue_reconsideration import (
                notify_applicant_review,
            )

            await notify_applicant_review(session, policy)
        return
    from backend.app.models.job import Job
    from backend.app.schemas.normalized_job import NormalizedJob
    from backend.app.services.job_ingestion import JobIngestionService

    item = NormalizedJob(
        source_name="naukri", source_job_id=value["requisition"], original_url=value["url"],
        title=observed.title, company_name=observed.company, location=observed.location,
        description=observed.description, skills_required=observed.skills,
        experience_min_years=observed.experience_min, experience_max_years=observed.experience_max,
        remote_type=observed.remote_type, employment_type=observed.employment_type,
        salary_min=observed.salary_min, salary_max=observed.salary_max,
        salary_currency=observed.salary_currency, salary_period=observed.salary_period,
        date_posted=observed.posted_at, source_verification_status="observed",
        data_provenance={"method": "bound_browser_ui", "evidence_sha256": observed.evidence_sha256,
                         "observed_at": (await instant(session)).isoformat(),
                         "posting_recruiter": observed.posting_recruiter, "experience_requirement": "required",
                         "observed_posted_date": observed.posted_date.isoformat() if observed.posted_date else None},
    )
    result = await JobIngestionService(session).ingest_jobs([item])
    if len(result.job_ids) != 1 or result.failed_count or result.rejected_count:
        value.update(stage="NEEDS_INPUT", status="waiting", reason="job_identity_requires_review")
        return
    from uuid import UUID

    job = await session.get(Job, UUID(result.job_ids[0]), populate_existing=True)
    if await store.previously_applied(session, job):
        value.update(stage="SKIPPED", status="complete", reason="prior_application_or_unknown_submission_no_replay")
        return
    # This exact provider observation is the latest listing view; canonical
    # title/company/history stay unchanged. Disagreements fail ingestion above.
    job.discovery_metadata = item.model_dump(mode="json")
    value["job_id"] = str(job.id)
    try:
        profile = await queue.eligible_context(session, value, policy, job)
    except ToolDenied as exc:
        queue.eligibility_hold(value, str(exc))
        return
    # Discovery owns filtering. Only a fully checked observation enters the
    # preparation lane; the independent worker still rechecks before any packet
    # or write, since the profile, policy or provider facts may have changed.
    value.update(stage="ELIGIBLE", operation="prepare", status="queued", reason=None,
                 profile_version=profile.version)
    await queue.event(session, value, "discovery_eligibility_verified")


async def dispatch(session, settings, actor, command):
    try:
        if actor.channel != "chrome" or actor.identity != settings.CHROME_EXTENSION_ID:
            raise ToolDenied("extension_identity_required")
        if command.command in {"naukri_queue_status", "naukri_queue_control"}:
            profile = await profiles.require_profile(session, command, read_only=command.command == "naukri_queue_status")
            if command.command == "naukri_queue_control":
                from backend.app.execution.queue_contracts import QueueControl

                if command.queue_action is None or command.expected_queue_revision is None:
                    raise ToolDenied("queue_control_fields_required")
                if command.queue_action == "start" and (not settings.CHROME_PROFILE_COMMANDS_ENABLED or not profile.value["commands_enabled"]):
                    raise ToolDenied("PROFILE_COMMANDS_DISABLED")
                await queue.control(session, QueueControl(action=command.queue_action, expected_revision=command.expected_queue_revision))
            status = await queue.listing(session, platform="naukri", limit=5)
            return Result(request_id=command.request_id, ok=True, capability="naukri_queue_controls",
                          data={"queue": {"state": status["configuration"]["state"], "revision": status["configuration"]["revision"],
                                          "counts": status["counts"], "total": status["total"], "consumer": status["consumer"]},
                                "submitted": False})
        if not settings.CHROME_PROFILE_COMMANDS_ENABLED:
            raise ToolDenied("PROFILE_COMMANDS_DISABLED")
        await store.memory_row(session, lock=True)
        if (await store.configuration(session)).mode == "OFF":
            raise ToolDenied("execution_mode_off")
        from backend.app.local_agent.policies import get_policy

        local_policy = await get_policy(session)
        if local_policy["platforms"].get("naukri", local_policy["default"]) == "disabled":
            raise ToolDenied("platform_disabled")
        profile = await profiles.require_profile(session, command)
        if not profile.value["commands_enabled"]:
            raise ToolDenied("PROFILE_COMMANDS_DISABLED")
        if command.window_id is None or command.window_id != profile.value["window_id"]:
            raise ToolDenied("queue_window_binding_changed")
        selected = await profiles.selection(session)
        binding = {
            "profile_binding_id": profile.value["id"], "profile_version": profile.value["version"],
            "selection_version": selected["version"], "browser_session_id": str(command.browser_session_id),
            "window_id": command.window_id, "tab_id": command.tab_id,
        }
        config = await queue.configuration(session)
        policy = QueuePolicy.model_validate(config["policy"])
        setting = policy.platforms.get("naukri")
        value = None
        if command.command == "poll_naukri_work":
            if config["state"] == "STOPPED":
                request = await session.get(OwnerPreference, MAINTENANCE, populate_existing=True)
                value = request.value if request else {}
                try:
                    expires = datetime.fromisoformat(value["expires_at"])
                    valid = timedelta(0) < expires - await instant(session) <= timedelta(minutes=2)
                    valid = valid and isinstance(value["request_id"], str) and str(UUID(value["request_id"])) == value["request_id"]
                except (KeyError, TypeError, ValueError):
                    valid = False
                maintenance_binding = {**binding, "tab_id": None}
                if (valid and value.get("kind") in {"open_extension_manager", "open_naukri_profile_setup"}
                        and value.get("binding") == maintenance_binding and setting and setting.enabled):
                    if value["kind"] == "open_naukri_profile_setup":
                        from backend.app.execution.naukri_identity import require

                        account = await require(session, profile_binding_id=binding["profile_binding_id"])
                        if (value.get("account_binding_revision") != account["revision"]
                                or value.get("candidate_profile_id") != account["candidate_profile_id"]):
                            raise ToolDenied("profile_setup_account_context_changed")
                        if command.tab_id is not None:
                            if (command.tab_id <= 0 or str(command.work_id) != value["request_id"]
                                    or value.get("opened_tab_id") not in {None, command.tab_id}):
                                raise ToolDenied("profile_setup_ack_context_changed")
                            adopted = False
                            if command.work_report is not None:
                                if (command.work_report.kind != "needs_input"
                                        or command.work_report.reason != "owner_tab_active"):
                                    raise ToolDenied("profile_setup_ack_report_invalid")
                                adopted = True
                            value = {**value, "opened_tab_id": command.tab_id,
                                     "owner_adopted": bool(value.get("owner_adopted") or adopted),
                                     "opened_at": value.get("opened_at") or (await instant(session)).isoformat()}
                            await queue.put(session, MAINTENANCE, value)
                            return Result(request_id=command.request_id, ok=True, capability="naukri_profile_setup",
                                          data={"work": None, "maintenance_recorded": True, "submitted": False})
                        if value.get("opened_tab_id") is not None:
                            return Result(request_id=command.request_id, ok=True, capability="naukri_profile_setup",
                                          data={"work": None, "maintenance_recorded": True, "submitted": False})
                    elif command.tab_id is not None:
                        raise ToolDenied("queue_poll_without_tab_required")
                    return Result(request_id=command.request_id, ok=True, capability="naukri_extension_maintenance",
                                  data={"work": None, "maintenance": {k: value[k] for k in ("kind", "request_id", "expires_at")},
                                        "submitted": False})
                value = None
            if command.tab_id is not None:
                raise ToolDenied("queue_poll_without_tab_required")
            if config["state"] == "RUNNING" and setting and setting.enabled:
                # Never overlap an owner's legacy command or a background read.
                from backend.app.browser import extension_tasks

                now = await instant(session)
                busy = any(r.value["state"] not in profiles.TERMINAL for r in await profiles.records(session, profiles.COMMAND))
                busy |= any(r.value["state"] in {"FORM_INSPECTED", "ANSWERS_REVIEWED", "FILL_AUTHORIZED", "FILLING"} for r in await extension_tasks.rows(session))
                leases = (await session.scalars(select(OwnerPreference.value["lease_until"].as_string()).where(
                    OwnerPreference.key.startswith(queue.PREFIX),
                    OwnerPreference.value["stage"].as_string().not_in(queue.TERMINAL),
                    OwnerPreference.value["status"].as_string().in_(["leased", "executing"]),
                ))).all()
                busy |= any(lease and datetime.fromisoformat(lease) > now for lease in leases)
                search = await session.get(OwnerPreference, SEARCH, populate_existing=True)
                busy |= bool(search and search.value.get("lease_until") and datetime.fromisoformat(search.value["lease_until"]) > now)
                sync = await session.get(OwnerPreference, profile_sync.WORK, populate_existing=True)
                busy |= bool(sync and sync.value.get("lease_until") and datetime.fromisoformat(sync.value["lease_until"]) > now)
                if not busy:
                    await submission.recover_unknown(session)
                    value = await queue.claim(session, "naukri", binding, operations=questionnaires.OPERATIONS)
                    if value is None:
                        value = await profile_sync.work(session, config, binding, settings)
                    if value is None:
                        value = await search_work(session, config, policy, binding)
                    if value is None:
                        value = await queue.claim(session, "naukri", binding, operations={"inspect_job"} | submission.READS)
                        if value and value["operation"] == "reconcile_application" and not submission.account_current(value, now):
                            value = {**value, "operation": "verify_account", "revision": value["revision"] + 1}
                            (await queue.load(session, value["id"])).value = value
                await queue.put(session, "apply_consumer:naukri", {
                    "last_poll_at": now.isoformat(), "profile_binding_id": profile.value["id"],
                    "busy": bool(busy), "capability": "ordinary_ui_direct_apply_candidate",
                })
            return Result(request_id=command.request_id, ok=True, capability="naukri_background_read",
                          data={"work": transport(value) if value else None, "submitted": False})
        if command.command == "bind_naukri_work":
            if command.tab_id is None:
                raise ToolDenied("queue_tab_binding_required")
            row = await checked(session, command, {**binding, "tab_id": None})
            value = {**row.value, "binding": binding, "revision": row.value["revision"] + 1}
        else:
            row = await checked(session, command, binding)
            value = dict(row.value)
            if command.command == "admit_naukri_work":
                if value["status"] != "leased" or command.tab_id is None:
                    raise ToolDenied("queue_action_already_admitted")
                if value["operation"] in {"inspect_profile", "inspect_application", "apply", "verify_account", "reconcile_application"}:
                    from backend.app.execution.naukri_identity import check_work

                    await check_work(session, value)
                if value["operation"] in profile_sync.OPERATIONS:
                    if value["operation"] == "sync_profile" and local_policy["platforms"].get("naukri", local_policy["default"]) in {"manual_only", "draft_only"}:
                        raise ToolDenied("platform_policy_requires_manual_review")
                    value = await profile_sync.admit(session, value)
                elif value["operation"] in {"apply", "answer_questionnaire"}:
                    value = await queue.admit(session, value["id"], value["revision"], value["lease_token"], binding, settings)
                    value = {**value, "permit_expires_at": ((await instant(session)) + timedelta(seconds=2)).isoformat()}
                else:
                    if value["operation"] in questionnaires.OPERATIONS:
                        await questionnaires.context(session, value, settings)
                    value.update(status="executing", revision=value["revision"] + 1)
            elif command.command in {"finish_naukri_work", "abandon_naukri_work"}:
                report = command.work_report
                if not report:
                    raise ToolDenied("queue_observation_required")
                if command.command == "finish_naukri_work" and value["status"] != "executing":
                    raise ToolDenied("queue_action_not_admitted")
                if value["operation"] in profile_sync.OPERATIONS:
                    continuing = await profile_sync.receive(session, value, report, settings)
                    value.update(revision=value["revision"] + 1)
                    if not continuing:
                        value.update(lease_token=None, lease_until=None)
                    row.value = value
                    return Result(request_id=command.request_id, ok=True, capability="naukri_profile_sync",
                                  data={"work": transport(value), "continue": continuing, "submitted": False})
                if value["operation"] in questionnaires.OPERATIONS:
                    if command.command == "abandon_naukri_work":
                        report = report.model_copy(update={"kind": "failed"})
                    await questionnaires.receive(session, value, report, settings)
                    continuing = value["status"] == "leased" and value["operation"] in questionnaires.OPERATIONS
                    value.update(updated_at=(await instant(session)).isoformat(), revision=value["revision"] + 1)
                    if not continuing:
                        value.update(lease_token=None, lease_until=None)
                    row.value = value
                    await queue.event(session, value, "questionnaire_browser_observed")
                    return Result(request_id=command.request_id, ok=True, capability="naukri_ui_execution",
                                  data={"work": transport(value), "continue": continuing, "submitted": False})
                if value["operation"] in submission.OPERATIONS:
                    if command.command == "abandon_naukri_work":
                        report = report.model_copy(update={"kind": "failed", "execution": None})
                    if value["operation"] == "reconcile_application":
                        value["reconciliation_attempts"] = value.get("reconciliation_attempts", 0) + 1
                    if value["operation"] == "verify_account":
                        value["account_recheck_attempts"] = value.get("account_recheck_attempts", 0) + 1
                    continuing = await submission.receive(session, value, report, settings)
                    value.update(updated_at=(await instant(session)).isoformat(), revision=value["revision"] + 1)
                    if not continuing:
                        value.update(lease_token=None, lease_until=None)
                    row.value = value
                    await queue.event(session, value, "browser_execution_observed")
                    return Result(request_id=command.request_id, ok=True, capability="naukri_ui_execution",
                                  data={"work": transport(value), "continue": continuing, "submitted": False})
                if report.kind not in {"needs_input", "failed", "job_facts", "source_candidates", "application_view"}:
                    raise ToolDenied("background_report_not_supported")
                if value["operation"] == "search_jobs":
                    if report.kind == "source_candidates":
                        if str(report.observed_url) != value["url"]:
                            raise ToolDenied("queue_document_identity_changed")
                        added = await queue.enqueue_batch(session, report.candidates, "naukri_ui_search")
                        value.update(candidates_found=value["candidates_found"] + added, last_cycle_count=added)
                    else:
                        value["last_error"] = report.reason or "source_observation_unavailable"
                    value.update(status="idle", last_finished_at=(await instant(session)).isoformat())
                elif report.kind in {"needs_input", "failed"}:
                    if (report.reason in TRANSIENT_DISCOVERY_ERRORS
                            and defer_transient_discovery(value, report.reason, await instant(session))):
                        pass
                    elif (report.reason == "owner_platform_active" and value["operation"] == "inspect_job"
                            and not value.get("admitted_actions") and not value.get("packet_id")
                            and not value.get("form_pending")):
                        # Owner activity can begin after poll but before DOM
                        # observation. Yield now; a new inactive tab may only
                        # inspect again after the existing activity gate clears.
                        # Never turn a form, packet or uncertain write into a
                        # retry, or require an owner answer for this read race.
                        now = await instant(session)
                        value.update(stage="FAILED_RETRYABLE", status="queued", reason=report.reason,
                                     available_at=(now + timedelta(seconds=60)).isoformat())
                    else:
                        value.update(stage="NEEDS_INPUT", status="waiting", reason=report.reason or "unsupported_provider_layout")
                else:
                    await receive_job(session, value, report)
                value.update(lease_token=None, lease_until=None, updated_at=(await instant(session)).isoformat(), revision=value["revision"] + 1)
            elif command.command != "check_naukri_work":
                raise ToolDenied("background_operation_not_supported")
        row.value = value
        return Result(request_id=command.request_id, ok=True, capability="naukri_background_read",
                      data={"work": transport(value), "submitted": False})
    except (ToolDenied, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ToolDenied) else "queue_invalid_provider_observation"
        return Result(request_id=command.request_id, ok=False, capability="naukri_background_read", error_code=reason)
