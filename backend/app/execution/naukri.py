"""No private Naukri APIs, credentials, cookies, or network dispatch.

Owner-supplied job/alert facts remain unverified. Official public documentation
establishes account features, not permission for third-party automation.
"""

import re
from urllib.parse import urlsplit, urlunsplit

from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.applications.platforms.base import safe_url

EVIDENCE = {
    "profile_applications": "https://www.naukri.com/blog/how-naukri-works/amp/",
    "alerts_history": "https://www.naukri.com/blog/greater-control-over-communication-from-naukri-com/",
}


def capability_matrix():
    return {
        "platform": "naukri",
        "live_verified": False,
        "discovery": "owner_supplied_urls_and_alert_facts",
        "account_profile_association": "local_session_manual_unverified",
        "job_alert_import": "owner_supplied_structured_facts",
        "application_history_import": "reviewed_mailbox_history_existing_owner_flow",
        "job_url_import": "supported_local_validation_only",
        "application_preparation": "saved_profile_resume_and_grounded_answers",
        "browser_form_assistance": "existing_owner_reviewed_engine_site_unverified",
        "submission_support": "manual_only_no_verified_naukri_contract",
        "public_jobseeker_api": "not_established",
        "background_source": "saved_owner_imports_only_no_portal_polling",
        "evidence": EVIDENCE,
    }


def normalized_url(url):
    checked = safe_url(url)
    if not checked:
        raise ValueError("public_https_job_url_required")
    p = urlsplit(checked)
    if p.hostname not in {"naukri.com", "www.naukri.com"}:
        raise ValueError("naukri_job_url_required")
    # Accept only a posting, never a login, search, profile or redirect endpoint.
    if not p.path.startswith("/job-listings-") or not re.search(
        r"-([0-9]{10,20})(?:/)?$", p.path
    ):
        raise ValueError("naukri_posting_path_required")
    return urlunsplit(("https", "www.naukri.com", p.path.rstrip("/"), "", ""))


def normalize(item):
    url = normalized_url(item.url)
    source_id = re.search(r"-([0-9]{10,20})$", url).group(1)
    if item.provenance == "owner_job_alert" and not item.message_reference:
        raise ValueError("alert_reference_required")
    if item.experience_requirement == "required" and item.experience_min is None:
        raise ValueError("required_experience_minimum_missing")
    return NormalizedJob(
        source_name="naukri",
        source_job_id=source_id,
        original_url=url,
        title=item.title,
        company_name=item.employer,
        description=item.description,
        location=item.location,
        remote_type=item.remote_type,
        skills_required=item.required_skills,
        skills_preferred=item.preferred_skills,
        experience_min_years=item.experience_min,
        experience_max_years=item.experience_max,
        salary_min=item.salary_min,
        salary_max=item.salary_max,
        salary_currency=item.salary_currency,
        salary_period=item.salary_period,
        data_provenance={
            "method": item.provenance,
            "reference": item.message_reference,
            "experience_requirement": item.experience_requirement,
            "provider_verified": False,
        },
        source_verification_status="requires_review",
    )
