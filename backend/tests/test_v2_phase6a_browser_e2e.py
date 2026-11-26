"""Phase 6A Layer 4 on a real headless Chromium (all network intercepted, nothing leaves the Mac):

  G. worker cycle: Instahyre session expired -> Keychain login -> auto email-OTP read via IMAP
     (EXAMINE/PEEK) -> logged in -> discover -> inspect -> live apply -> APPLIED receipt
  H. BrowserService.process_job on Greenhouse + Lever: unknown required question -> Telegram/dashboard
     HITL -> owner answer -> priority re-run -> APPLIED; APPLIED is never replayed
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter
from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter
from backend.app.browser_v2.adapters.lever import LeverAdapter
from backend.app.browser_v2.auth import AutoLogin, LoginSpec, MemoryVault
from backend.app.browser_v2.hitl import HITLResolutionService
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerControl, WorkerState
from backend.app.browser_v2.worker import Worker
from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.reader import ImapReadClient, MailReadService
from backend.tests.phase6a_fixtures import (  # noqa: F401
    PDF,
    chromium_fixture,
    days_ago,
    html,
    web_fixture,
)
from backend.tests.test_adapters_phase6 import (
    GH_JOB,
    LEVER_FORM,
    LEVER_ID,
    ZETA_ID,
    gh_form,
    instahyre_job,
    lever_api,
)
from backend.tests.test_browser_v2_auth import LOGIN_PAGE
from backend.tests.test_mail_v2_reader import FakeIMAP, rfc822

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]


class PageManager:
    running = True

    def __init__(self, page):
        self._page = page

    @asynccontextmanager
    async def job(self):
        yield self._page

    async def maybe_recycle_between_jobs(self, max_age_sec=10800):
        return False

    async def close(self):
        return None


def profile(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(PDF)
    return {"full_name": "Test Candidate", "email": "candidate@example.com", "phone": "+910000000000",
            "verified_experience_years": 3, "verified_skills": ["Python", "FastAPI"],
            "preferences": {"target_roles": ["Python Developer", "Backend Engineer"], "willing_to_relocate": True,
                            "current_location": "Bengaluru", "skill_years": {"python": 3},
                            "resume_files": {"backend": str(resume)}}}


async def test_pipeline_g_auto_otp_login_recovery_then_live_instahyre_apply(web, tmp_path):
    page, site = web
    now = datetime.now(UTC)
    home = "https://www.instahyre.com/candidate/opportunities"
    logged_in = {"value": False}

    def opportunities(request):
        if "otp=ok" in request.url:
            logged_in["value"] = True  # only the verified OTP step logs the session in
        if not logged_in["value"]:
            return html("<script>location.href='/login'</script>")
        return html('<a href="/candidate/profile/">Profile</a><div class="job-card">'
                    '<a href="/job-283941-python-developer-at-acme-bangalore/">Python Developer</a>'
                    '<span class="company-name">Acme</span><span>Posted 2 days ago</span><span>45 applicants</span></div>')

    def login_page(_request):
        return LOGIN_PAGE.replace("<script>", "<script>window.NEED_OTP = true;").replace(
            "=== '482913') location.href = '/candidate/opportunities'",
            "=== '482913') location.href = '/candidate/opportunities?otp=ok'")

    site.add(home, opportunities)
    site.add("https://www.instahyre.com/login", login_page)
    site.add("https://www.instahyre.com/job-283941-python-developer-at-acme-bangalore", instahyre_job())
    imap = FakeIMAP([rfc822("Instahyre <noreply@instahyre.com>", "Your login code", "Your OTP is 482913",
                            minutes_ago=0)])
    imap_config = MailConfig(imap_email="owner@example.com", imap_password="TEST_FAKE_TOKEN_ONLY")
    reader = MailReadService(imap_config, imap=ImapReadClient(imap_config, factory=imap), clock=lambda: now)
    store = MemoryStore(rules={"instahyre": PortalRules("instahyre", enabled=True, auto_apply_enabled=True,
                                                        active_hours_start=None, active_hours_end=None)},
                        profile=profile(tmp_path), worker=WorkerControl(desired_state=WorkerState.RUNNING,
                                                                        dry_run=False))
    adapter = InstahyreAdapter(receipts_root=tmp_path, settle_ms=20, refresh_wait_ms=10, jitter=(0, 0),
                               confirm_timeout_s=3)
    service = BrowserService(PageManager(page), store, {"instahyre": adapter})
    service.auto_login = AutoLogin(MemoryVault({"instahyre": ("owner@example.com", "TEST_FAKE_TOKEN_ONLY")}),
                                   reader, specs={"instahyre": LoginSpec("https://www.instahyre.com/login")},
                                   settle_ms=50, otp_timeout_s=3)

    async def no_sleep(seconds):
        return None

    worker = Worker(service, sleeper=no_sleep, idle_poll_sec=0.01, inspection_pause_sec=(0, 0))
    report = await worker.cycle(await store.get_worker_control())
    portal = report.portals[0]
    assert {"auto_login": "password+email_otp"} in portal.outcomes, portal
    assert not await store.open_hitl_exists("instahyre", "AUTH")  # solved without waking the owner
    record = await store.get("instahyre", "283941")
    assert record is not None and record.state is S.APPLIED, (portal, record)
    assert record.receipt["source"].startswith("confirmation_text")
    assert all(call[0] != "store" for call in imap.calls)  # inbox read-only (EXAMINE + PEEK)


async def test_pipeline_h_greenhouse_and_lever_hitl_round_trip_to_applied(web, tmp_path):
    page, site = web
    site.add(GH_JOB, gh_form())
    site.add(GH_JOB + "/confirmation", html("<h2>Thank you for applying!</h2>"))
    zeta = f"https://jobs.lever.co/zeta/{ZETA_ID}"
    site.add(zeta + "/apply", LEVER_FORM.replace(f"/acme/{LEVER_ID}", f"/zeta/{ZETA_ID}"))
    site.add(zeta + "/thanks", html("<h2>Application submitted!</h2>"))

    def greenhouse_api(request):
        return httpx.Response(200, json={"jobs": [{"id": 4012345, "title": "Backend Engineer", "absolute_url": GH_JOB,
                                                   "location": {"name": "Remote"}, "content": "Python FastAPI",
                                                   "first_published": days_ago(1)}]})

    store = MemoryStore(rules={"greenhouse": PortalRules("greenhouse", enabled=True, auto_apply_enabled=True),
                               "lever": PortalRules("lever", enabled=True, auto_apply_enabled=True)},
                        profile=profile(tmp_path))
    async with httpx.AsyncClient(transport=httpx.MockTransport(greenhouse_api)) as gh_client, \
            httpx.AsyncClient(transport=httpx.MockTransport(lever_api)) as lever_client:
        greenhouse = GreenhouseAdapter(http_client=gh_client, receipts_root=tmp_path, settle_ms=10,
                                       confirm_timeout_s=5, boards={"acme": "Acme"})
        lever = LeverAdapter(http_client=lever_client, receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=5,
                             boards={"acme": "Acme"})
        service = BrowserService(PageManager(page), store, {"greenhouse": greenhouse, "lever": lever})
        [listing] = await service.discover_listings("greenhouse", "Backend Engineer")
        first = await service.process_job(listing, dry_run=False)
        assert first["state"] == "WAITING_FOR_USER" and first["hitl_request_id"]
        hitl = await store.get_hitl(first["hitl_request_id"])
        assert hitl.prompt_text == "Are you legally authorized to work in India?" and hitl.options == ("Yes", "No")
        resolution = await HITLResolutionService(store, None).answer(hitl.id, "Yes", cache_answer=False,
                                                                     via="telegram")
        assert resolution.ok and (await store.get("greenhouse", "4012345")).state is S.SCORED
        [requeued] = await store.requeued_applications("greenhouse")
        second = await service.process_job(listing, dry_run=False)
        assert second["state"] == "APPLIED" and second["receipt"]["ats"] == "greenhouse", second
        assert requeued.external_job_id == "4012345"
        again = await service.process_job(listing, dry_run=False)
        assert again["refused"] == "never_replay:APPLIED"

        [lever_listing] = await service.discover_listings("lever", "Backend Engineer")
        duplicate = await service.process_job(lever_listing, dry_run=False)  # same role @ Acme already APPLIED
        assert duplicate["state"] == "FILTERED_OUT" and duplicate["reason"].startswith("duplicate_of: greenhouse:")
        lever.boards = {"zeta": "Zeta"}
        lever.jobs.clear()
        lever._feed_cache.clear()
        [lever_listing] = await service.discover_listings("lever", "Backend Engineer")
        dry = await service.process_job(lever_listing, dry_run=True)
        assert dry["reason"] == "dry_run_stopped_before_submit" and (
            await store.get("lever", lever_listing.external_job_id)).state is S.DISCOVERED
        live = await service.process_job(lever_listing, dry_run=False)
        assert live["state"] == "APPLIED" and (await store.get("lever", lever_listing.external_job_id)).applied_at
    events = [e["reason"] for e in store.events]
    assert events.count("apply_started") == 3 and "confirmed" in events
    assert (datetime.now(UTC) - timedelta(minutes=5)) < (await store.get("greenhouse", "4012345")).applied_at
