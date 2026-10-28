"""Separate browser process with short transactions and lease checks before every action."""

import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from backend.app.browser import queue
from backend.app.browser.contracts import FillReceipt, Inspection
from backend.app.browser.service import FormService, pdf_bytes


class ChromeDriver:
    def __init__(self, profile, headless=False):
        self.profile, self.headless, self.process = str(profile), headless, None

    async def call(self, operation, **payload):
        if self.process is None:
            self.process = await asyncio.create_subprocess_exec(
                "node",
                str(Path(__file__).with_name("driver.mjs")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=8 * 1024 * 1024,
            )
        async with asyncio.timeout(30):
            self.process.stdin.write(
                (json.dumps({"operation": operation, **payload}) + "\n").encode()
            )
            await self.process.stdin.drain()
            line = await self.process.stdout.readline()
            if not line:
                raise RuntimeError("browser_disconnected")
            return json.loads(line)

    async def abort(self):
        if self.process and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()
        self.process = None

    async def close(self):
        if self.process and self.process.returncode is None:
            try:
                await self.call("close")
                await asyncio.wait_for(self.process.wait(), 5)
            except (Exception, TimeoutError):
                self.process.kill()
                await self.process.wait()
        self.process = None


class BrowserWorker:
    def __init__(self, factory, settings, driver):
        self.factory, self.settings, self.driver = factory, settings, driver
        self.active = {}  # Browser document identity is intentionally never recovered after a crash.

    async def run_once(self):
        from backend.app.browser.submission_worker import SubmissionWorker
        submission = await SubmissionWorker(self.factory, self.settings, self.driver).run_once()
        if submission:
            return submission
        from backend.app.automation.store import instant
        from backend.app.dashboard.models import OwnerPreference
        from backend.app.services.discovery_budget import insert_for

        async with self.factory() as session:
            now = await instant(session)
            await session.execute(
                insert_for(session)(OwnerPreference)
                .values(
                    key="browser_worker:primary",
                    value={"heartbeat_at": now.isoformat()},
                )
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": {"heartbeat_at": now.isoformat()}},
                )
            )
            claimed = await queue.claim(session)
            await session.commit()
        if not claimed:
            return None
        key, job = claimed
        try:
            async with asyncio.timeout(65):
                result = await self.work(key, job)
        except Exception:
            result = {
                "status": "manual_required",
                "error_code": "browser_interrupted_check_form_manually",
                "submitted": False,
            }
        async with self.factory() as session:
            try:
                row, current = await queue.fenced(session, key, job["fence"])
            except ValueError:
                await self.driver.close()
                return {"status": "cancelled", "submitted": False}
            current.update(state=result["status"], result=result, lease_until=None)
            if result.get("plan_id"):
                current["plan_id"] = result["plan_id"]
            row.value = current
            await queue.finish_campaign(session, current)
            await session.commit()
        return result

    async def work(self, key, job):
        async with self.factory() as session:
            await queue.fenced(session, key, job["fence"])
            service = FormService(session, self.settings)
            packet, _, url = await service.context(UUID(job["application_id"]))
            await session.commit()
        if job.get("next_requested"):
            if key not in self.active:
                return {
                    "status": "manual_required",
                    "error_code": "browser_restarted_reinspect_required",
                    "submitted": False,
                }
            async with self.factory() as session:
                await queue.fenced(session, key, job["fence"])
                _, previous = await FormService(session, self.settings).load(
                    UUID(job["plan_id"])
                )
                await FormService(session, self.settings).fresh(previous)
            progressed = await self.driver.call("next", document_id=self.active[key])
            if progressed.get("violations") or progressed.get("state") != "progressed":
                return {
                    "status": "manual_required",
                    "error_code": "unsafe_step_transition",
                    "submitted": False,
                }
            async with self.factory() as session:
                row, current = await queue.fenced(session, key, job["fence"])
                plan = await FormService(session, self.settings).inspect(
                    UUID(job["application_id"]),
                    Inspection.model_validate(progressed["inspection"]),
                    "local_automation",
                    job["selected_project"],
                )
                self.active[key] = plan.inspection.document_id
                current["next_requested"] = False
                row.value = current
                await session.commit()
            return {
                "status": "awaiting_review",
                "plan_id": str(plan.id),
                "submitted": False,
            }
        if job["plan_id"]:
            if key not in self.active:
                return {
                    "status": "manual_required",
                    "error_code": "browser_restarted_reinspect_required",
                    "submitted": False,
                }
            plan_id = UUID(job["plan_id"])
        else:
            from backend.app.browser.runner import validate_destination

            # Recheck configured permission and public DNS before opening a
            # generic employer URL. DOM contents cannot supply this grant.
            if self.settings.ENVIRONMENT != "testing":
                await validate_destination(url, self.settings)
            opened = await self.driver.call(
                "open",
                url=url,
                profile=self.driver.profile,
                headless=self.driver.headless,
                permitted_origin=urlsplit(url).scheme + "://" + urlsplit(url).netloc,
                fixture_origin=self.settings.BROWSER_FIXTURE_ORIGIN
                if self.settings.ENVIRONMENT == "testing"
                else None,
            )
            if not opened.get("inspection") or opened.get("violations"):
                return {
                    "status": "manual_required",
                    "error_code": "unexpected_navigation_or_network",
                    "submitted": False,
                }
            inspection = Inspection.model_validate(opened["inspection"])
            if inspection.state not in {"ready", "validation_errors"}:
                return {
                    "status": "manual_required",
                    "reason": inspection.state,
                    "submitted": False,
                }
            async with self.factory() as session:
                await queue.fenced(session, key, job["fence"])
                plan = await FormService(session, self.settings).inspect(
                    UUID(job["application_id"]),
                    inspection,
                    "local_automation",
                    job["selected_project"],
                )
                await session.commit()
            plan_id = plan.id
            self.active[key] = plan.inspection.document_id
            if job["inspect_only"]:
                return {
                    "status": "form_inspected",
                    "plan_id": str(plan.id),
                    "missing_fields": [
                        a.field_id for a in plan.actions if a.needs_input
                    ],
                    "missing_information": [
                        f.label or f.field_id
                        for a, f in zip(plan.actions, plan.inspection.fields)
                        if a.needs_input
                    ],
                    "submitted": False,
                }
            if any(a.requires_review and not a.needs_input for a in plan.actions):
                return {
                    "status": "awaiting_review",
                    "plan_id": str(plan.id),
                    "submitted": False,
                }
            async with self.factory() as session:
                await queue.fenced(session, key, job["fence"])
                await FormService(session, self.settings).review(
                    plan.id, [a.field_id for a in plan.actions if not a.needs_input]
                )
                await session.commit()
        async with self.factory() as session:
            await queue.fenced(session, key, job["fence"])
            service = FormService(session, self.settings)
            plan, packet = await service.consume(plan_id, "local_automation")
            raw = await pdf_bytes(session, packet, self.settings)
            await (
                session.commit()
            )  # Consume durably before crossing the browser boundary.
        async with self.factory() as session:
            await queue.fenced(session, key, job["fence"])
        actions = [
            a.model_dump(mode="json")
            for a in plan.actions
            if a.field_id in plan.approved_fields
        ]
        result = {"state": "form_filled", "results": [], "violations": 0}
        if actions:
            # Consume one approved batch: the DOM guard permits exactly one fill
            # per inspected document and rechecks changes between field mutations.
            async with self.factory() as session:
                await queue.fenced(session, key, job["fence"])
                await FormService(session, self.settings).fresh(plan)
                part = await self.driver.call(
                    "fill",
                    document_id=plan.inspection.document_id,
                    actions=actions,
                    pdf=base64.b64encode(raw).decode()
                    if raw and any(action["kind"] == "file" for action in actions)
                    else None,
                )
                await session.commit()
            result["results"].extend(part.get("results", []))
            if part.get("violations") or part.get("state") in {
                "manual_required",
                "failed",
            }:
                result.update(
                    state="manual_required", violations=part.get("violations", 0)
                )
            elif part.get("state") != "form_filled":
                result["state"] = "needs_input"
        receipt = FillReceipt(
            plan_id=plan.id,
            results=result.get("results", []),
            state=result.get("state", "failed"),
        )
        async with self.factory() as session:
            await queue.fenced(session, key, job["fence"])
            await FormService(session, self.settings).receipt(receipt)
            await session.commit()
        status = (
            "manual_required"
            if result.get("violations")
            else "needs_input"
            if not actions
            or any(
                (a.needs_input or a.field_id not in plan.approved_fields) and f.required
                for a, f in zip(plan.actions, plan.inspection.fields)
            )
            else receipt.state
        )
        if status == "form_filled" and self.settings.ENVIRONMENT == "testing" and self.settings.BROWSER_FIXTURE_ORIGIN:
            from backend.app.agent.tools import ToolDenied
            from backend.app.browser.submission import SubmissionService
            from backend.app.browser.submission_adapters import fixture_contract
            try:
                fixture_contract(plan.target_url, self.settings, "pending")
                snapshot = await self.driver.call("submission_review", document_id=plan.inspection.document_id, actions=actions)
                async with self.factory() as session:
                    await SubmissionService(session, self.settings).create_review(plan.id, UUID(job["campaign_id"]), snapshot)
                    await session.commit()
            except (ToolDenied, ValueError):
                pass  # Unsupported forms remain fill-only; no submission grant is manufactured.
        return {
            "status": status,
            "confirmation_required": True,
            "missing_information": [
                f.label or f.field_id
                for a, f in zip(plan.actions, plan.inspection.fields)
                if a.needs_input
            ],
            "plan_id": str(plan.id),
            "fields": [r.model_dump() for r in receipt.results],
            "submitted": False,
        }
