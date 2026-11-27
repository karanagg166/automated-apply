"""Milestone 2 (offline): pre-submit vs post-submit timeout quota accounting, Greenhouse emailed
security codes (mail side) and the resume-variant picker aliases."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.browser_v2.adapters.base import (
    ApplyResult,
    AuthStatus,
    JobDetail,
    JobListing,
    SessionCheck,
)
from backend.app.browser_v2.adapters.shared.security_code import (
    code_question,
    needs_security_code,
    obtain_code,
    owner_prompt,
)
from backend.app.browser_v2.redact import redact_secrets
from backend.app.browser_v2.resume import pick_resume, variant_used
from backend.app.browser_v2.rules import PortalRules, parse_applicants
from backend.app.browser_v2.service import BrowserService, quota_counts
from backend.app.browser_v2.state import APPLY_ELIGIBLE
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerControl, WorkerState
from backend.app.browser_v2.submit_marker import (
    mark_submit_attempted,
    submit_attempted,
    submit_scope,
)
from backend.app.mail_v2.read_models import MailMessage, MailReadError
from backend.app.mail_v2.security_codes import (
    extract_security_code,
    find_security_code,
    mask_code,
    normalize_company,
    poll_security_code,
    security_code_provider,
)
from backend.tests.phase6a_fixtures import PDF

SUBMIT = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)


# --- submit marker ------------------------------------------------------------------------------------------
async def test_submit_marker_scope_is_isolated_per_apply():
    assert not submit_attempted()
    mark_submit_attempted()  # outside a scope: harmless no-op
    with submit_scope() as first:
        assert not first.attempted
        mark_submit_attempted("final_submit")
        assert submit_attempted() and first.label == "final_submit" and first.attempted_at is not None
    with submit_scope() as second:
        assert not second.attempted
    assert not submit_attempted()


class FakeManager:
    running = True

    @asynccontextmanager
    async def job(self):
        yield object()

    async def maybe_recycle_between_jobs(self, max_age_sec: int = 10800) -> bool:
        return False


class HangingAdapter:
    """Applies by hanging either before or after the (marked) submit click."""

    platform = "greenhouse"

    def __init__(self, *, mark_before_hang: bool, tracks: bool = True) -> None:
        self.mark_before_hang = mark_before_hang
        self.tracks_submit = tracks

    async def check_session(self, page):
        return SessionCheck(AuthStatus.OK)

    async def discover_jobs(self, page, *, query, limit=20, job_age_days=None):
        return []

    async def inspect_job(self, page, listing):
        return JobDetail(listing=listing, applicants=parse_applicants("10 applicants"), posted_age_days=1,
                         already_applied=False, apply_mode="direct", description="python fastapi backend",
                         apply_url=listing.url, ats="greenhouse")

    async def extract_form(self, page):
        return {}

    async def detect_portal_limit(self, page):
        return None

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        if self.mark_before_hang:
            mark_submit_attempted("greenhouse_submit")
        await asyncio.sleep(30)  # the browser hangs; the worker's wall clock cancels it
        return ApplyResult(S.APPLIED, "confirmed", dry_run)


def make_service(adapter) -> tuple[BrowserService, MemoryStore, PortalRules]:
    rules = PortalRules(platform="greenhouse", enabled=True, auto_apply_enabled=True, active_hours_start=None,
                        active_hours_end=None, max_applies_per_day=1, max_applies_per_hour=1)
    store = MemoryStore(rules={"greenhouse": rules},
                        profile={"preferences": {"target_roles": ["Backend Engineer"]}},
                        worker=WorkerControl(desired_state=WorkerState.RUNNING, dry_run=False))
    return BrowserService(FakeManager(), store, adapters={"greenhouse": adapter}), store, rules  # type: ignore[arg-type]


LISTING = JobListing(platform="greenhouse", external_job_id="4012345",
                     url="https://job-boards.greenhouse.io/acme/jobs/4012345", title="Backend Engineer",
                     company="Acme", posted_age_days=1)


async def run_with_timeout(service: BrowserService) -> None:
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(service.process_job(LISTING, dry_run=False, record_filters=True), timeout=0.2)


async def test_pre_submit_timeout_is_retryable_failed_and_burns_no_quota():
    service, store, rules = make_service(HangingAdapter(mark_before_hang=False))
    await run_with_timeout(service)
    record = await store.get("greenhouse", "4012345")
    assert record is not None and record.state is S.FAILED and record.state in APPLY_ELIGIBLE
    events = [e for e in store.events if e["to"] == S.FAILED]
    assert events and str(events[-1]["reason"]).startswith("FAILED_TIMEOUT:pre_submit:CancelledError")
    counts = await quota_counts(store, rules)
    assert counts["attempts_today"] == 0 and not counts["daily_limit_hit"]


async def test_repeated_pre_submit_hangs_stop_retrying_after_the_attempt_cap():
    from backend.app.browser_v2.service.apply import MAX_PRE_SUBMIT_ATTEMPTS

    service, store, rules = make_service(HangingAdapter(mark_before_hang=False))
    for _ in range(MAX_PRE_SUBMIT_ATTEMPTS):
        await run_with_timeout(service)
    record = await store.get("greenhouse", "4012345")
    assert record is not None and record.state is S.FILTERED_OUT
    assert record.reason == "pre_submit_failures_exhausted"
    counts = await quota_counts(store, rules)
    assert counts["attempts_today"] == 0


async def test_timeout_after_the_submit_click_stays_submission_unknown_and_counts():
    service, store, rules = make_service(HangingAdapter(mark_before_hang=True))
    await run_with_timeout(service)
    record = await store.get("greenhouse", "4012345")
    assert record is not None and record.state is S.SUBMISSION_UNKNOWN
    counts = await quota_counts(store, rules)
    assert counts["attempts_today"] == 1 and counts["daily_limit_hit"]


async def test_uninstrumented_adapter_keeps_the_safe_submission_unknown_default():
    service, store, _ = make_service(HangingAdapter(mark_before_hang=False, tracks=False))
    await run_with_timeout(service)
    record = await store.get("greenhouse", "4012345")
    assert record is not None and record.state is S.SUBMISSION_UNKNOWN


def test_instrumented_adapters_declare_submit_tracking():
    from backend.app.browser_v2.service import default_adapters

    adapters = default_adapters()
    for name in ("naukri", "greenhouse", "lever", "ashby", "instahyre", "internshala", "wellfound"):
        assert getattr(adapters[name], "tracks_submit", False), name


# --- Greenhouse security codes: mail side -----------------------------------------------------------------
def gh_mail(key: str, minutes: float, *, code: str = "Ab3dE9fG", company: str = "Acme",
            sender: str = "no-reply@us.greenhouse-mail.io") -> MailMessage:
    return MailMessage(key, f"Greenhouse <{sender}>", f"Security code for your application to {company}",
                       SUBMIT + timedelta(minutes=minutes),
                       f"Copy and paste this code into the security code field on your {company} application: "
                       f"{code}", "imap")


class FakeReader:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = 0

    async def recent(self, since, *, sender_domain=None, limit=40):
        self.calls += 1
        batch = self.batches[min(self.calls - 1, len(self.batches) - 1)]
        if isinstance(batch, Exception):
            raise batch
        return batch


async def no_sleep(_seconds: float) -> None:
    return None


def test_code_extraction_ignores_plain_words_and_normalizes_companies():
    assert extract_security_code("Enter this security code: Ab3dE9fG to finish") == "Ab3dE9fG"
    assert extract_security_code("Use the security code field on the page") is None
    assert normalize_company("Acme Technologies Pvt. Ltd.") == "acme" and mask_code("Ab3dE9fG") == "<code len=8>"


async def test_newest_matching_code_wins_and_old_or_foreign_codes_are_ignored():
    reader = FakeReader([[gh_mail("old", -5, code="OLD1code"),  # sent before this submit: never reused
                          gh_mail("a", 0.5, code="Fst1Code"),
                          gh_mail("b", 1.5, code="New2Code"),
                          gh_mail("other", 2, code="Oth3Code", company="Globex"),  # another company
                          gh_mail("spoof", 3, code="Spf4Code", sender="alerts@greenhouse.example")]])
    hit = await find_security_code(reader, "Acme Inc.", SUBMIT - timedelta(seconds=10))
    assert hit is not None and hit.code == "New2Code" and hit.message_key == "b"


async def test_wrong_company_only_yields_nothing_and_poll_times_out():
    reader = FakeReader([[gh_mail("other", 1, company="Globex")]])
    code = await poll_security_code(reader, "Acme", SUBMIT, timeout_s=15, interval_s=5, sleep=no_sleep)
    assert code is None and reader.calls == 4  # t=0,5,10,15


async def test_poll_returns_the_code_once_it_arrives_and_never_logs_it(caplog):
    caplog.set_level(logging.INFO)
    reader = FakeReader([[], [], [gh_mail("late", 1, code="Lat5Code")]])
    code = await poll_security_code(reader, "Acme", SUBMIT, timeout_s=120, interval_s=5, sleep=no_sleep)
    assert code == "Lat5Code" and reader.calls == 3
    assert "Lat5Code" not in caplog.text and "<code len=8>" in caplog.text
    assert "Lat5Code" not in redact_secrets("Greenhouse security code: Lat5Code")


async def test_mail_unavailable_falls_back_to_the_owner_hitl():
    reader = FakeReader([MailReadError("mail_read_unconfigured")])
    provide = security_code_provider(reader, {"GREENHOUSE_OTP_TIMEOUT_SECONDS": "5"})
    assert await provide("Acme", SUBMIT) is None
    code, source = await obtain_code(provide, "Acme", SUBMIT, None)
    assert (code, source) == (None, "security_code_timeout")
    owner = {owner_prompt("Acme"): " Own6Code "}
    assert await obtain_code(provide, "Acme", SUBMIT, owner) == ("Own6Code", "owner_hitl")
    assert await obtain_code(None, "Acme", SUBMIT, None) == (None, "security_code_mail_unavailable")
    question = code_question("Acme", "https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse", "x")
    assert question.kind == "OTP" and question.context["priority"] == "P0"


def test_security_prompt_detection():
    assert needs_security_code({"body": "A verification code was sent to your email. Enter it below."})
    assert not needs_security_code({"body": "Thank you for applying", "confirmed": True})
    assert not needs_security_code({"body": "Upload your resume"})


# --- resume variants ---------------------------------------------------------------------------------------
def test_resume_variant_aliases_and_default_fallback(tmp_path):
    files = {}
    for name in ("default", "backend", "fullstack", "ai_ml"):
        path = tmp_path / f"{name}.pdf"
        path.write_bytes(PDF)
        files[name] = str(path)
    ai = pick_resume(files, title="Machine Learning Engineer", description="LLM RAG pipelines with PyTorch")
    assert ai.label == "ai_ml" and ai.reason == "best_keyword_match"
    full = pick_resume(files, title="Full Stack Developer", description="React and Next.js")
    assert full.label == "fullstack"
    none = pick_resume(files, title="Office Manager", description="Coordinate facilities")
    assert none.label == "default" and none.reason == "default_variant"
    only = pick_resume({"default": files["default"]}, title="Backend Engineer", description=None)
    assert only.label == "default"


def test_resume_variant_used_from_answers():
    answers = [{"question": "Resume", "answer": "ai_ml.pdf", "source": "resume_picker", "variant": "ai_ml"}]
    assert variant_used(answers) == "ai_ml"
    assert variant_used([{"question": "Q", "answer": "Yes", "source": "profile"}],
                        uploaded_fallback="portal_profile") == "portal_profile"
