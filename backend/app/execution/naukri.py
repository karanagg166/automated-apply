"""No private Naukri APIs, credentials, cookies, or network dispatch.

Owner-supplied job/alert facts remain unverified. Official public documentation
establishes account features, not permission for third-party automation.
"""

import re
from datetime import datetime
from types import SimpleNamespace
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
        "discovery": "background_ui_observer_and_approved_alert_queue_source_candidate",
        "account_profile_association": "local_session_manual_unverified",
        "job_alert_import": "opt_in_approved_gmail_candidates_then_verified_facts",
        "application_history_import": "reviewed_mailbox_history_existing_owner_flow",
        "job_url_import": "supported_local_validation_only",
        "application_preparation": "saved_profile_resume_and_grounded_answers",
        "browser_form_assistance": "existing_owner_reviewed_engine_site_unverified",
        "submission_support": "ordinary_ui_direct_apply_candidate_no_live_acceptance",
        "recurring_submission": {
            "state": "BLOCKED_TECHNICAL",
            "reason": "submission_resume_receipt_and_locked_acceptance_pending",
            "enabled": False,
            "platform_permission_status": "not_established",
            "owner_requires_provider_outreach": False,
        },
        "resume_upload": {
            "canonical_pdf_preflight": "integrated_with_packet_preparation",
            "unattended_worker_verified": False,
            "native_chooser_path": "NEEDS_HUMAN",
            "upload_control_initialization_required": True,
            "file_selection_may_submit": True,
            "locked_screen_verified": False,
        },
        "public_jobseeker_api": "not_established",
        "background_source": "normal_ui_search_and_approved_local_alerts_not_live_accepted",
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
    if not re.fullmatch(
        r"/job-listings-[a-zA-Z0-9%_-]+-[0-9]{10,20}/?", p.path
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
        application_url=str(item.application_url) if item.application_url else None,
        title=item.title,
        company_name=item.employer,
        description=item.description,
        location=item.location,
        remote_type=item.remote_type,
        employment_type=item.employment_type,
        skills_required=item.required_skills,
        skills_preferred=item.preferred_skills,
        experience_min_years=item.experience_min,
        experience_max_years=item.experience_max,
        salary_min=item.salary_min,
        salary_max=item.salary_max,
        salary_currency=item.salary_currency,
        salary_period=item.salary_period,
        date_posted=item.posted_at,
        data_provenance={
            "method": item.provenance,
            "reference": item.message_reference,
            "experience_requirement": item.experience_requirement,
            "provider_verified": False,
            "posting_status": item.posting_status,
            "owner_observed_at": item.observed_at.isoformat() if item.observed_at else None,
            "valid_through": item.valid_through.isoformat() if item.valid_through else None,
        },
        source_verification_status="requires_review",
    )

def matching_job(job):
    """Use the latest explicit re-import without changing human-edited Job columns."""
    observed = job.discovery_metadata or {}
    view = SimpleNamespace(**vars(job))
    if observed.get("source_name") == "naukri":
        for target, source in {
            "title": "title", "description": "description", "location": "location",
            "skills_required": "skills_required", "remote_type": "remote_type",
            "employment_type": "employment_type", "salary_min": "salary_min",
            "experience_level": "experience_level",
            "salary_max": "salary_max", "salary_currency": "salary_currency",
            "salary_period": "salary_period",
            "application_url": "application_url",
        }.items():
            setattr(view, target, observed.get(source))
        view.is_remote = view.remote_type == "remote"
        try:
            view.date_posted = datetime.fromisoformat(observed["date_posted"])
        except (KeyError, TypeError, ValueError):
            view.date_posted = None
    return view


def reviewed_job_context(job, company):
    """Use one reviewed listing for matching, policy, packets and answers.

    Canonical Job/Company rows retain human history. An owner-reviewed employer
    correction is listing evidence, not proof that the old company's domain or
    enrichment belongs to the newly named employer.
    """
    view = matching_job(job)
    observed = job.discovery_metadata or {}
    if observed.get("source_name") != "naukri":
        return job, company
    name = observed.get("company_name")
    same_employer = bool(
        company and name
        and " ".join(company.name.casefold().split())
        == " ".join(name.casefold().split())
    )
    if not same_employer:
        company = SimpleNamespace(
            id=None, name=name, domain=None, metadata_={}
        ) if name else None
        view.company_id = None
    return view, company
