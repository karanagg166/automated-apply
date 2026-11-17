//! Closed normalized paid-job finding; provider claims never become live or eligibility evidence.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
fn invalid() -> Failure {
    Failure("invalid_apify_job_finding")
}
pub(super) fn project(
    value: &Value,
    source: &str,
    limit: u64,
    now: DateTime<Utc>,
) -> Result<Value> {
    if value.to_string().len() > 8388608
        || value["source"] != source
        || !crate::source_registry::APIFY_PORTALS.contains(&source)
        || value["application_dispatch"] != false
        || value["live_verified"] != false
        || value["billing_final"] != false
    {
        return Err(invalid());
    }
    let at = crate::job_sources::access::time(&value["observed_at"])?;
    if at > now || !(1..=100).contains(&limit) {
        return Err(invalid());
    }
    let jobs = value["jobs"]
        .as_array()
        .filter(|a| a.len() as u64 <= limit)
        .ok_or_else(invalid)?;
    let rejected = value["rejected_count"]
        .as_u64()
        .filter(|n| *n <= 100)
        .ok_or_else(invalid)?;
    let duplicates = value["duplicate_count"]
        .as_u64()
        .filter(|n| *n <= 100)
        .ok_or_else(invalid)?;
    if jobs.len() as u64 + rejected + duplicates > limit {
        return Err(invalid());
    }
    if value["status"]
        != if rejected > 0 {
            "partial"
        } else if jobs.is_empty() {
            "no_results"
        } else {
            "success"
        }
    {
        return Err(invalid());
    }
    let mut selected = Vec::new();
    for job in jobs {
        let job =
            crate::job_sources::contract::normalize(job.clone(), at).map_err(|_| invalid())?;
        if job["source_name"] != source
            || job["source_verification_status"] != "source_reported"
            || job["is_confirmed_current"] != false
        {
            return Err(invalid());
        }
        let provenance = &job["data_provenance"];
        if provenance.as_object().is_none_or(|m| {
            m.keys().any(|k| {
                !matches!(
                    k.as_str(),
                    "adapter" | "portal" | "actor_id" | "provider_run_id" | "actor_build"
                )
            })
        }) || provenance["adapter"] != "ApifyJobAdapter"
            || provenance["portal"] != source
        {
            return Err(invalid());
        }
        for field in ["actor_id", "provider_run_id", "actor_build"] {
            if provenance[field]
                .as_str()
                .is_none_or(|s| s.is_empty() || s.len() > 200)
            {
                return Err(invalid());
            }
        }
        let intel = job["company_intelligence"]
            .as_object()
            .ok_or_else(invalid)?;
        if intel.keys().any(|k| {
            !matches!(
                k.as_str(),
                "stage"
                    | "batch"
                    | "technologies"
                    | "remote_policy"
                    | "source"
                    | "verification_status"
            )
        }) {
            return Err(invalid());
        }
        if !intel.is_empty()
            && (job["company_intelligence"]["source"] != source
                || job["company_intelligence"]["verification_status"] != "source_reported")
        {
            return Err(invalid());
        }
        for key in ["stage", "batch", "technologies", "remote_policy"] {
            if let Some(v) = intel.get(key) {
                let valid = v.is_null()
                    || v.as_str().is_some_and(|s| s.chars().count() <= 2000)
                    || key == "technologies"
                        && v.as_array().is_some_and(|a| {
                            a.len() <= 100
                                && a.iter()
                                    .all(|v| v.as_str().is_some_and(|s| s.chars().count() <= 200))
                        });
                if !valid {
                    return Err(invalid());
                }
            }
        }
        selected.push(job);
    }
    Ok(
        json!({"source":source,"status":value["status"],"jobs":selected,"rejected_count":rejected,"duplicate_count":duplicates,"observed_at":value["observed_at"],"batch_complete":true,"billing_final":false,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_apify_dataset_selected_job_claims"}),
    )
}
