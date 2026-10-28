"""Compare explicit listing ranges only. Role titles do not establish required years."""

from backend.app.schemas.normalized_job import NormalizedJob


def experience_fit(job, approved_years):
    metadata = job.discovery_metadata or {}
    try:
        # Revalidate persisted source evidence; malformed legacy values stay unknown.
        evidence = NormalizedJob(
            source_name=job.source_platform, original_url=job.job_url, title=job.title,
            experience_min_years=metadata.get("experience_min_years"),
            experience_max_years=metadata.get("experience_max_years"),
        )
    except ValueError:
        return "unknown"
    if approved_years is None or evidence.experience_min_years is None:
        return "unknown"
    if approved_years < evidence.experience_min_years:
        return "below_minimum"
    if evidence.experience_max_years is not None and approved_years > evidence.experience_max_years:
        return "outside_published_range"
    return "within_published_range"
