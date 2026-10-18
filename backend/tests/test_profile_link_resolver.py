from types import SimpleNamespace
from uuid import uuid4
import pytest

from backend.app.core.config import Settings
from backend.app.services.profile_link_resolver import ProfileLinkResolver


def resource(kind="resume", label="Backend resume", primary=True, confirmed=True):
    return SimpleNamespace(id=uuid4(), resource_type=kind, label=label, url="https://drive.google.com/file/d/example/view", is_primary=primary, user_confirmed=confirmed)


@pytest.mark.parametrize("question,expected", [
    ("Provide your GitHub", "https://github.com/example"), ("GitHub profile link?", "https://github.com/example"),
    ("Please share your GIT HUB URL!", "https://github.com/example"),
    ("Original LinkedIn profile URL", "https://www.linkedin.com/in/example"),
    ("Portfolio website", "https://example.com/portfolio"),
])
def test_exact_and_alternate_questions(phase2_profile, question, expected):
    resolver = ProfileLinkResolver(phase2_profile, [], Settings(_env_file=None))
    result = resolver.resolve(question)
    assert result.answer == expected and result.confidence == 1 and not result.requires_review


def test_resume_url_and_file_upload():
    item = resource()
    resolver = ProfileLinkResolver(None, [item], Settings(_env_file=None))
    assert resolver.resolve("Share your resume link").answer == item.url
    result = resolver.resolve("Upload your latest resume")
    assert result.status == "file_upload_required" and result.answer is None
    assert result.resources[0]["accessibility"] == "not_checked"


def test_missing_ambiguous_custom_labels():
    general, backend = resource(label="General resume", primary=False), resource(primary=False)
    resolver = ProfileLinkResolver(None, [general, backend], Settings(_env_file=None))
    assert resolver.resolve("Resume URL").status == "needs_input"
    assert resolver.resolve("Backend resume link").answer == backend.url
    assert resolver.resolve("GitHub and resume URLs").status == "needs_input"
    assert resolver.resolve("GitHub profile").answer is None
    assert resolver.resolve("Describe a project on GitHub").answer is None
    custom = resource(kind="other", label="Research notebook")
    assert ProfileLinkResolver(None, [custom], Settings(_env_file=None)).resolve("Research notebook link").answer == custom.url


def test_env_fallback_and_saved_authority(phase2_profile):
    settings = Settings(_env_file=None, CANDIDATE_GITHUB_URL="https://github.com/env-example", CANDIDATE_LEETCODE_URL="https://leetcode.com/u/example")
    resolver = ProfileLinkResolver(phase2_profile, [], settings)
    assert resolver.resolve("github").answer == phase2_profile.github_url
    result = resolver.resolve("LeetCode profile?")
    assert result.source == "environment_default" and result.requires_review and result.confidence < 1
    phase2_profile.github_url, phase2_profile.version = None, 2
    assert resolver.resolve("github").answer is None


def test_unconfirmed_or_unsafe_links_do_not_resolve():
    item = resource(confirmed=False)
    settings = Settings(_env_file=None, CANDIDATE_RESUME_DRIVE_URL="https://example.com/default")
    assert ProfileLinkResolver(None, [item], settings).resolve("resume").answer is None
    item.user_confirmed, item.url = True, "http://example.com/legacy"
    assert ProfileLinkResolver(None, [item], settings).resolve("resume").answer is None


@pytest.mark.parametrize("question", ["GitHub username", "GitHub repositories", "GitHub and phone", "GitHub project URL"])
def test_specific_or_compound_requests_do_not_guess(phase2_profile, question):
    result = ProfileLinkResolver(phase2_profile, [], Settings(_env_file=None)).resolve(question)
    assert result.status == "needs_input" and result.answer is None
