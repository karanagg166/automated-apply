"""URL eligibility does not establish live website compatibility or permission."""

import pytest

from backend.app.browser.service import target
from backend.app.browser.site_policy import application_page_url
from backend.app.core.config import Settings
from backend.app.services.applications.platforms.owner_page import manual_page_url

ATS_URLS = [
    "https://job-boards.greenhouse.io/fictional/jobs/12345",
    "https://jobs.lever.co/fictional/fictional-job-123/apply",
    "https://jobs.eu.lever.co/fictional/fictional-job-123",
    "https://jobs.ashbyhq.com/fictional/fictional-job-123/application",
    "https://jobs.smartrecruiters.com/Fictional/12345678-engineer",
    "https://fictional.wd5.myworkdayjobs.com/en-US/External/job/Bengaluru/Engineer_R12345",
    "https://docs.google.com/forms/d/e/fictional/viewform",
]


@pytest.mark.parametrize("url", ATS_URLS)
def test_shared_url_eligibility_covers_documented_host_shapes(url):
    settings = Settings(_env_file=None)
    assert application_page_url(url) == url
    assert manual_page_url(url, settings) == url
    assert target(url, settings) == url


@pytest.mark.parametrize("url", [
    "https://jobs.ashbyhq.com.evil.example/fictional/id",
    "https://jobs.smartrecruiters.com@evil.example/Fictional/12345678-engineer",
    "https://fictional.wd5.myworkdayjobs.com.evil.example/job/123",
    "https://jobs.ashbyhq.com/fictional/id?token=private",
    "http://127.0.0.1/apply", "https://10.0.0.1/apply",
    "https://simplify.jobs/p/fictional", "https://www.linkedin.com/jobs/123",
    "https://accounts.google.com/login", "https://mail.google.com/mail/u/0",
])
def test_unreviewed_and_restricted_destinations_cannot_be_enabled_by_generic_grant(url):
    assert application_page_url(url) is None
    assert application_page_url(url, ["https://simplify.jobs:443", "https://www.linkedin.com:443"]) is None


def test_generic_html_or_react_employer_requires_exact_origin_grant():
    url = "https://fictional-employer.example/careers/apply"
    assert manual_page_url(url, Settings(_env_file=None)) is None
    settings = Settings(_env_file=None, BROWSER_ALLOWED_ORIGINS=["https://fictional-employer.example:443"])
    assert manual_page_url(url, settings) == target(url, settings) == url
    assert manual_page_url("https://other.example/careers/apply", settings) is None
    assert manual_page_url(url + "?session=private", settings) is None
