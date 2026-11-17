//! Local-only reconstruction from every hash-bound selected page; no transport or current-scope substitution.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;
fn invalid() -> Failure {
    Failure("apify_read_selected_pages_invalid")
}
pub(super) fn project(original: &Value, read: &Value, now: DateTime<Utc>) -> Result<Option<Value>> {
    let Some(pages) = read.get("selected_pages") else {
        return Ok(None);
    };
    let pages = pages
        .as_array()
        .filter(|a| !a.is_empty() && a.len() <= 2)
        .ok_or_else(invalid)?;
    if read["operation"]["kind"] != "dataset"
        || read["operation"]["state"] != "retained"
        || !matches!(
            read["state"].as_str(),
            Some("response_retained" | "finding_retained")
        )
        || read["failure_codes"]
            .as_array()
            .is_none_or(|a| !a.is_empty())
    {
        return Ok(None);
    }
    let run = &read["selected_run"];
    let build = &read["selected_build"];
    if read["selected_run_hash"] != crate::python_json::digest(run)
        || read["selected_run_hash"] != original["selected_run_hash"]
        || read["selected_build_hash"] != crate::python_json::digest(build)
        || original["read_observation"]["schema"] != 1
        || original["read_observation"]["billing_final"] != false
        || original["read_observation"]["independent_termination_verified"] != false
        || original["read_observation"]["read_request_id"] != read["read_request_id"]
        || original["read_observation"]["selected_run_hash"] != read["selected_run_hash"]
        || run["status"] != "SUCCEEDED"
        || run["id"] != original["reservation"]["provider_run_id"]
        || build["id"] != run["buildId"]
        || build["run_id"] != run["id"]
        || build["input_schema_available"] != true
        || build["live_verified"] != false
        || build["schema_digest"]
            .as_str()
            .is_none_or(|s| s.len() != 64 || !s.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        return Err(invalid());
    }
    let source = original["source"].as_str().ok_or_else(invalid)?;
    let limit = original["effective_query"]["limit"]
        .as_u64()
        .filter(|n| (1..=100).contains(n))
        .ok_or_else(invalid)?;
    let mut selection = super::dataset::Selection::default();
    let mut at = None;
    let mut complete = false;
    for (index, saved) in pages.iter().enumerate() {
        let page = &saved["page"];
        let offset = index as u64 * 50;
        let observed = crate::job_sources::access::time(&page["observed_at"])?;
        if saved["hash"] != crate::python_json::digest(page)
            || offset >= limit
            || page["offset"] != offset
            || page["limit"] != 50.min(limit - offset)
            || observed > now
            || at.is_some_and(|at| at != observed)
            || complete
        {
            return Err(invalid());
        }
        at = Some(observed);
        let returned = page["returned"]
            .as_u64()
            .filter(|n| *n <= 50.min(limit - offset))
            .ok_or_else(invalid)?;
        for job in page["jobs"].as_array().ok_or_else(invalid)? {
            if job["source_name"] != source
                || job["data_provenance"]["provider_run_id"] != run["id"]
                || job["data_provenance"]["actor_build"] != run["buildNumber"]
                || crate::apify_config::safe_actor(
                    job["data_provenance"]["actor_id"]
                        .as_str()
                        .ok_or_else(invalid)?,
                )? != original["selected_actor"]["alias"]
                    .as_str()
                    .ok_or_else(invalid)?
            {
                return Err(invalid());
            }
        }
        selection.push(page)?;
        complete = returned < 50.min(limit - offset) || offset + returned >= limit;
    }
    if !complete {
        return Ok(None);
    }
    let finding = selection.finding(source, at.ok_or_else(invalid)?);
    Ok(Some(super::finding::project(&finding, source, limit, now)?))
}
