"""Local URL validation cannot establish live authorization, availability or submission."""

from types import SimpleNamespace

import pytest

from backend.app.services.applications.platforms.naukri import NaukriPlatform


def job(**kwargs):
    return SimpleNamespace(
        **{
            "source_platform": "naukri",
            "job_url": "https://www.naukri.com/example-job",
            "application_url": None,
            "status": "discovered",
            "source_verification_status": "observed",
            **kwargs,
        }
    )


def test_capability_honest_owner_assisted_manual_submission():
    capability = NaukriPlatform().capabilities()
    assert (
        capability.submission_mode == "manual_handoff"
        and capability.live_verified is False
    )
    assert capability.automated_submission == "not_authorized_or_verified"
    assert capability.browser_autofill == "assisted_native_fields"


@pytest.mark.parametrize(
    "url",
    ["https://www.naukri.com/example-job", "https://jobs.example.org/apply/backend"],
)
def test_valid_saved_destinations_preserved(url):
    destination = NaukriPlatform().destination(job(application_url=url))
    assert destination.application_url == url and destination.valid
    assert destination.kind == (
        "naukri_hosted" if "naukri.com" in url else "employer_external"
    )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://example.org/job",
        "https://user:pass@example.org/job",
        "https://127.0.0.1/job",
        "https://10.0.0.1/job",
        "https://example.local/job",
        "https://example.org:8443/job",
    ],
)
def test_unsafe_destination_is_never_handed_off(url):
    destination = NaukriPlatform().destination(job(application_url=url))
    assert not destination.valid and destination.application_url is None


@pytest.mark.parametrize("status", ["expired", "invalid", "closed"])
def test_closed_source_not_ready(status):
    assert (
        not NaukriPlatform().destination(job(source_verification_status=status)).valid
    )


def test_spoofed_source_and_host_suffix_do_not_match():
    adapter = NaukriPlatform()
    assert not adapter.recognizes(
        job(source_platform="other", job_url="https://naukri.com.attacker.example/job")
    )
    result = adapter.destination(
        job(
            job_url="https://naukri.com.attacker.example/job",
            application_url="https://example.org/apply",
        )
    )
    assert result.source_confidence == "source_conflict"


@pytest.mark.parametrize("expiry", ["2026-02-10", "not-a-date"])
def test_expiry_evidence_overrides_active_observation_and_apply_control(expiry):
    from datetime import datetime, timezone

    from backend.app.services.applications.platforms.naukri import posting_unavailable

    posting = job(discovery_metadata={"data_provenance": {"posting_status": "active", "valid_through": expiry}})
    assert posting_unavailable(posting, datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert not NaukriPlatform().destination(posting).valid
