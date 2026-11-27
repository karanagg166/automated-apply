"""Phase 9 go-live fixes: seniority filter for entry-level owners, feed lookup beyond the LRU cap,
backlog rows keep their posting age."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.browser_v2.adapters.feeds import CACHE_LIMIT, FeedAdapter, FeedJob
from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.rules import (
    CandidatePreferences,
    Decision,
    evaluate_preferences,
)
from backend.app.browser_v2.rules.preferences import senior_title_marker
from backend.app.browser_v2.worker.executor import ExecutorMixin

ENTRY = CandidatePreferences(target_roles=("Software Engineer", "Backend Engineer", "AI Engineer"),
                             max_required_experience_years=0.0)


@pytest.mark.parametrize("title", [
    "Senior Backend Engineer - Subscriptions", "Principal Backend Engineer, Platform", "Sr. Software Engineer",
    "Backend Engineer Manager - Fintech", "Staff Software Engineer", "Lead AI Engineer", "Software Engineer II",
    "Software Engineer 3", "SDE-2 Backend", "Backend Engineer III", "Intermediate Backend Engineer",
])
def test_senior_titles_are_filtered_for_entry_level(title: str) -> None:
    result = evaluate_preferences(title=title, company="Acme", description=None, salary_text=None,
                                  work_mode=None, prefs=ENTRY)
    assert result.decision is Decision.FILTERED and result.reasons[0].startswith("title_seniority_above_profile")


@pytest.mark.parametrize("title", [
    "Software Engineer", "Software Engineer I", "Backend Engineer (New Grad)", "AI Engineer - Early Career",
    "Associate Software Engineer", "Software Engineer, Data Warehouse Analytics",
])
def test_entry_titles_pass(title: str) -> None:
    result = evaluate_preferences(title=title, company="Acme", description=None, salary_text=None,
                                  work_mode=None, prefs=ENTRY)
    assert result.decision is Decision.PASS, result.reasons


def test_seniority_filter_only_for_entry_level_ceiling() -> None:
    experienced = CandidatePreferences(target_roles=("Backend Engineer",), max_required_experience_years=5.0)
    unset = CandidatePreferences(target_roles=("Backend Engineer",))
    for prefs in (experienced, unset):
        result = evaluate_preferences(title="Senior Backend Engineer", company="Acme", description=None,
                                      salary_text=None, work_mode=None, prefs=prefs)
        assert result.decision is Decision.PASS
    assert senior_title_marker("Head of Engineering") == "head" and senior_title_marker("Software Engineer") is None


class ManyJobsFeed(FeedAdapter):
    platform = "greenhouse"

    def __init__(self, total: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.total = total

    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        return [FeedJob(external_job_id=str(i), url=f"https://example.test/jobs/{i}", title=f"Engineer {i}", apply_url=None,
                        company="Acme") for i in range(self.total)]


async def test_lookup_finds_a_job_even_when_the_feed_exceeds_the_cache_cap(tmp_path: Any) -> None:
    adapter = ManyJobsFeed(CACHE_LIMIT * 3, receipts_root=tmp_path)
    job = await adapter.lookup(JobListing(platform="greenhouse", external_job_id="7", url="https://example.test/jobs/7"))
    assert job is not None and job.external_job_id == "7"
    assert len(adapter.jobs) <= CACHE_LIMIT


def test_backlog_listing_keeps_posting_age() -> None:
    posted = datetime.now(UTC) - timedelta(days=2, hours=1)
    record = SimpleNamespace(platform="lever", external_job_id="x", job_url="https://jobs.lever.co/a/x",
                             role_title="Software Engineer", company_name="Acme", posted_at=posted)
    listing = ExecutorMixin.backlog_listing(record)
    assert listing.posted_age_days == 2 and listing.posted_at == posted
    legacy = SimpleNamespace(platform="lever", external_job_id="y", job_url=None, role_title=None,
                             company_name=None, posted_at=None)
    assert ExecutorMixin.backlog_listing(legacy).posted_age_days is None


def test_multi_role_query_matches_any_target_role() -> None:
    from backend.app.browser_v2.adapters.shared.text import (
        multi_role_query,
        role_query_match,
    )

    query = multi_role_query(["Backend Engineer", "AI Engineer", " ", "Software Development Engineer"])
    assert query == "Backend Engineer | AI Engineer | Software Development Engineer"
    assert role_query_match("Applied AI Engineer, Enterprise AI", query)
    assert role_query_match("Backend Developer (Python)", query)  # engineer ~ developer synonym
    assert not role_query_match("Account Executive", query)
    assert role_query_match("Anything", "") and role_query_match("Backend Engineer", "Backend Engineer")


def test_worker_uses_one_all_roles_query_for_whole_feed_adapters_only() -> None:
    from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter
    from backend.app.browser_v2.adapters.himalayas import HimalayasAdapter

    prefs = CandidatePreferences(target_roles=("Backend Engineer", "AI Engineer"))
    worker = SimpleNamespace(service=SimpleNamespace(adapters={"greenhouse": GreenhouseAdapter(),
                                                               "himalayas": HimalayasAdapter()}),
                             query_index={})
    assert ExecutorMixin.next_query(worker, "greenhouse", prefs) == "Backend Engineer | AI Engineer"  # type: ignore[arg-type]
    rotating = [ExecutorMixin.next_query(worker, "himalayas", prefs) for _ in range(3)]  # type: ignore[arg-type]
    assert rotating == ["Backend Engineer", "AI Engineer", "Backend Engineer"]
    assert GreenhouseAdapter.whole_feed and not HimalayasAdapter.whole_feed


@pytest.mark.parametrize(("label", "key"), [
    ("What is your Legal Name?", "full_name"), ("Full legal name", "full_name"), ("Legal name", "full_name"),
    ("Name", "full_name"), ("First name", "first_name"), ("What is your favourite name for a pet?", None),
])
def test_identity_labels(label: str, key: str | None) -> None:
    from backend.app.browser_v2.adapters.shared.form_filler import identity_key

    assert identity_key({"label": label}) == key


def test_role_country_localizes_authorization_question() -> None:
    from backend.app.browser_v2.adapters.shared.text import (
        localize_role_country,
        role_country,
    )
    from backend.app.browser_v2.answers import resolve_answer

    assert role_country("Bengaluru, India") == "India" and role_country("Pune") == "India"
    assert role_country("Remote") is None and role_country("San Francisco, CA") is None
    question = "Are you legally authorized to work in the country in which this role is located?"
    india = localize_role_country(question, SimpleNamespace(location="Bengaluru, India"))
    assert india == "Are you legally authorized to work in India?"
    assert localize_role_country(question, SimpleNamespace(location=None)) == question
    from backend.app.browser_v2.answers import CandidateFacts as Facts

    facts = Facts.from_profile({"preferences": {"work_authorizations": [
        {"country_name": "India", "country_code": "IN", "authorized_to_work": True,
         "requires_sponsorship_now_or_future": False}]}})
    assert resolve_answer(india, ("Yes", "No"), facts) == "Yes"
    assert resolve_answer("Are you authorized to work in the US?", ("Yes", "No"), facts) is None  # owner decides
