"""One shared durable executor for Telegram and dashboard commands.

Only discovery and opt-in understanding cross transaction boundaries. Local
preparation and its progress commit atomically, so replay cannot duplicate packets.
"""
import asyncio
from contextlib import suppress
from uuid import UUID

from backend.app.agent import store
from backend.app.agent.contracts import Approval, ToolCall
from backend.app.agent.discovery import discover
from backend.app.agent.planner import (
    CommandPlanner,
    deterministic,
    explicit_preparation,
)
from backend.app.agent.tools import ToolDenied, ToolExecutor
from backend.app.automation.store import instant
from backend.app.local_agent.contracts import Actor, page_kind
from backend.app.models.job import Job


def actor_for(campaign):
    channel, identity = campaign.actor.split(":", 1)
    return Actor(channel=channel, identity=identity)


async def draft_grant(session, campaign):
    platforms = set()
    for job_id in campaign.plan.selected_jobs:
        job = await session.get(Job, job_id)
        if job:
            platforms.add(page_kind(job.application_url or job.job_url))
    return Approval(expected_revision=campaign.revision, nonce=campaign.approval_nonce, scope="prepare",
                    platforms=sorted(platforms) or ["employer_forms"],
                    maximum_applications=max(1, len(campaign.plan.selected_jobs)))


def summary(campaign):
    search = next((r for r in campaign.results if r.get("tool") in {"search_jobs", "filter_jobs"}), None)
    prepared = sum(r.get("tool") == "prepare_application" and r.get("status") == "prepared" for r in campaign.results)
    missing = sum(r.get("tool") == "prepare_application" and r.get("status") == "needs_input" for r in campaign.results)
    errors = sum(r.get("status") in {"denied", "failed", "manual_required", "capability_not_enabled"} for r in campaign.results)
    lines = []
    if search:
        lines.append(f"Checked {search['scanned']} saved jobs. {search['matched']} match your filters; {search['unknown']} have unknown eligibility.")
        for i, row in enumerate(campaign.ranked_jobs, 1):
            lines.append(f"{i}. {row['title']} — {row.get('company') or 'Company unknown'} ({row['source']}, {row['verification_status']})")
    if prepared or missing:
        lines.append(f"{prepared} application drafts are ready for review; {missing} need missing information.")
    if errors:
        lines.append(f"{errors} actions need manual intervention or were denied.")
    if campaign.plan.missing_information:
        lines.extend(campaign.plan.missing_information)
    if campaign.diagnostic:
        lines.append("Pending/unavailable: " + campaign.diagnostic.replace("_", " "))
    for result in campaign.results:
        if result.get("tool") == "get_application_history":
            apps = result.get("applications", [])
            lines.append(f"{len(apps)} recent saved applications; {sum(a['readiness'] in {'needs_input', 'needs_resume'} for a in apps)} need information.")
        if result.get("tool") == "get_approved_project_context":
            if result.get("projects"):
                lines.append("Approved project selected: " + result["projects"][0]["name"] + ".")
            else:
                lines.extend(result.get("missing_information", []))
    lines.append("Zero submissions were made. No emails were sent.")
    return "\n".join(lines)[:3400]


class CommandExecutor:
    def __init__(self, factory, settings, planner=None):
        self.factory, self.settings = factory, settings
        self.planner = planner or CommandPlanner(settings)

    async def run_once(self):
        async with self.factory() as session:
            from backend.app.dashboard.models import OwnerPreference
            from backend.app.services.discovery_budget import insert_for
            now = await instant(session)
            await session.execute(insert_for(session)(OwnerPreference).values(key="agent_worker:primary",
                value={"heartbeat_at": now.isoformat()}).on_conflict_do_update(index_elements=["key"],
                set_={"value": {"heartbeat_at": now.isoformat()}}))
            campaign = await store.claim(session)
            await session.commit()
        if campaign is None:
            return None
        pulse = asyncio.create_task(self._pulse(campaign))
        try:
            async with asyncio.timeout(180):
                await self._work(campaign)
        except ToolDenied:
            # Cancellation/expired fencing is not an executable failure or permission to retry.
            pass
        except (Exception, TimeoutError):
            async with self.factory() as session:
                try:
                    row, current = await store.fenced(session, campaign.id, campaign.fence)
                    store.transition(current, "queued" if current.attempts < 3 else "failed", await instant(session), "bounded_execution_failure")
                    current.diagnostic, current.lease_until = "execution_unavailable", None
                    current.reply = "Execution unavailable; retained for bounded recovery. Zero submissions were made."
                    store.save(row, current)
                    await store.notify(session, current)
                    await session.commit()
                except ToolDenied:
                    pass
        finally:
            pulse.cancel()
            with suppress(asyncio.CancelledError, ToolDenied):
                await pulse
        async with self.factory() as session:
            return (await store.load(session, campaign.id))[1]

    async def _pulse(self, campaign):
        while True:
            await asyncio.sleep(25)
            await store.heartbeat(self.factory, campaign.id, campaign.fence)

    async def _work(self, claimed):
        async with self.factory() as session:
            _, campaign = await store.fenced(session, claimed.id, claimed.fence)
            memory = store.bounded_memory(await store.memory_row(session), await instant(session))
        if not campaign.planned:
            # Unknown usage after a crashed planning request cannot authorize another cloud attempt.
            started = any(h.get("reason") == "understanding_started" for h in campaign.history)
            local = deterministic(campaign.message)
            if started and local is None:
                understanding, tokens = await CommandPlanner(self.settings).understand("", {})
                understanding.missing_information = ["Previous AI response was lost. Clarify using a deterministic command."]
            else:
                async with self.factory() as session:
                    row, current = await store.fenced(session, claimed.id, claimed.fence)
                    current.history.append({"reason": "understanding_started", "at": (await instant(session)).isoformat()})
                    store.save(row, current)
                    await session.commit()
                understanding, tokens = await self.planner.understand(campaign.message, memory)
            plan = self.planner.plan(understanding, memory)
            async with self.factory() as session:
                row, campaign = await store.fenced(session, claimed.id, claimed.fence)
                campaign.understanding, campaign.plan, campaign.planned = understanding, plan, True
                campaign.tokens_used = tokens if tokens is not None else plan.max_tokens
                campaign.selected_project = memory.get("selected_project")
                if understanding.intent == "select_project":
                    campaign.plan.actions = [ToolCall(name="get_approved_project_context", arguments={"project": understanding.project, "purpose": "owner_selection"})]
                if understanding.intent == "status":
                    campaign.plan.actions = [ToolCall(name="get_application_history", arguments={"limit": 10})]
                if understanding.intent == "approve":
                    campaign.plan.missing_information = ["Use 'Prepare applications for the first three' to authorize drafts for saved results, or review the exact campaign in Agent. Submission is unavailable."]
                if understanding.intent == "cancel":
                    campaign.plan.missing_information = ["No previous campaign is available to cancel."]
                if understanding.intent == "apply" and not plan.missing_information:
                    if local is not None and explicit_preparation(campaign.message):
                        campaign.approval = await draft_grant(session, campaign)
                    else:
                        store.transition(campaign, "awaiting_approval", await instant(session), "draft_scope_clarification_required")
                        campaign.reply = "Preparation can create local drafts only. Submission is unavailable. Say 'Prepare applications for the first three' to authorize drafts, or approve this exact campaign in Agent."
                        campaign.lease_until = None
                        store.save(row, campaign)
                        await store.notify(session, campaign)
                        await session.commit()
                        return
                if tokens is None or tokens >= plan.max_tokens:
                    campaign.plan.actions = []
                    campaign.plan.missing_information = ["AI usage is unknown or exceeds this campaign's token budget. Clarify with a deterministic command."]
                store.save(row, campaign)
                await session.commit()
        # External discovery has its own idempotent durable run. No LLM can choose a transport.
        if campaign.plan.intent == "search" and campaign.plan.filters.source != "cached" and not any(
                r.get("tool") == "discovery" for r in campaign.results) and not campaign.plan.missing_information:
            result = await discover(self.factory, self.settings, campaign)
            async with self.factory() as session:
                row, campaign = await store.fenced(session, claimed.id, claimed.fence)
                campaign.results.append({"tool": "discovery", **result})
                if result["status"] not in {"success", "partial", "no_results", "cached"}:
                    campaign.diagnostic = "discovery_" + result["status"]
                    campaign.plan.actions = []
                store.save(row, campaign)
                await session.commit()
        while True:
            async with self.factory() as session:
                memory_record = await store.memory_row(session, lock=True)
                row, campaign = await store.fenced(session, claimed.id, claimed.fence)
                memory = store.bounded_memory(memory_record, await instant(session))
                if campaign.next_step >= len(campaign.plan.actions):
                    await self._finish(session, row, campaign, memory_record, memory)
                    await session.commit()
                    return
                action = campaign.plan.actions[campaign.next_step]
                executor = ToolExecutor(session, self.settings, actor_for(campaign), campaign, memory)
                async with asyncio.timeout(45):
                    result = await executor.execute(action, campaign.next_step)
                campaign.results.append({"tool": action.name, **result})
                campaign.next_step += 1
                if action.name == "prepare_application":
                    campaign.applications[str(action.arguments["job_id"])] = result
                if action.name == "get_approved_project_context" and len(result.get("projects", [])) == 1:
                    campaign.selected_project = result["projects"][0]["project_id"]
                if action.name == "rank_jobs" and campaign.understanding.prepare_count:
                    count = campaign.understanding.prepare_count
                    selected = [UUID(j["job_id"]) for j in campaign.ranked_jobs[:count]]
                    campaign.plan.selected_jobs = selected
                    # Only the deterministic compound grammar permits immediate draft creation.
                    if deterministic(campaign.message) is not None and explicit_preparation(campaign.message):
                        campaign.approval = await draft_grant(session, campaign)
                        campaign.plan.actions.extend(ToolCall(name="prepare_application", arguments={"job_id": str(j)}) for j in selected)
                    elif selected:
                        campaign.plan.missing_information.append("Confirm draft preparation for the saved ranked results.")
                store.save(row, campaign)
                if campaign.state == "cancelled":
                    await store.notify(session, campaign)
                await session.commit()

    async def _finish(self, session, row, campaign, memory_record, memory):
        now = await instant(session)
        incomplete = campaign.diagnostic or campaign.plan.missing_information or any(
            r.get("status") in {"needs_input", "denied", "failed", "manual_required", "capability_not_enabled"} for r in campaign.results)
        state = "partially_completed" if incomplete else "completed"
        store.transition(campaign, state, now, "execution_finished")
        campaign.lease_until, campaign.reply = None, summary(campaign)
        if campaign.plan.intent in {"search", "filter"} and not campaign.diagnostic and not campaign.plan.missing_information:
            memory.update(agent_filters=campaign.plan.filters.model_dump(mode="json"),
                          job_ids=[r["job_id"] for r in campaign.ranked_jobs],
                          candidate_ids=[str(i) for i in campaign.candidate_ids], result_campaign=str(campaign.id))
        if campaign.selected_project:
            memory["selected_project"] = campaign.selected_project
        memory.update(last_campaign=str(campaign.id), updated_at=now.isoformat())
        if memory.get("pending_campaign") == str(campaign.id):
            memory.pop("pending_campaign", None)
        memory_record.value = memory
        store.save(row, campaign)
        await store.notify(session, campaign)


async def run_worker(factory, settings, stop=None):
    stop = stop or asyncio.Event()
    executor = CommandExecutor(factory, settings)
    while not stop.is_set():
        result = await executor.run_once()
        if result is None:
            try:
                await asyncio.wait_for(stop.wait(), 2)
            except TimeoutError:
                pass
