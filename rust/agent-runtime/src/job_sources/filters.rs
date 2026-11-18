//! Explicit discovery filters preserve unknown fields; they never establish Apply eligibility.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;
fn words<'a>(query: &'a Value, key: &str) -> Result<Vec<&'a str>> {
    query[key]
        .as_array()
        .ok_or(Failure("invalid_discovery_query"))?
        .iter()
        .map(|v| v.as_str().ok_or(Failure("invalid_discovery_query")))
        .collect()
}
pub fn exclusion(
    item: &Value,
    explicit: &Value,
    effective: &Value,
    now: DateTime<Utc>,
) -> Result<Option<&'static str>> {
    let explicit = super::contract::query(explicit.clone())?;
    let effective = super::contract::query(effective.clone())?;
    let item = super::contract::normalize(item.clone(), now)?;
    if let Some(days) = effective["max_age_days"].as_i64()
        && let Some(at) = crate::packet_record::expiry(&item["date_posted"])
            .map_err(|_| Failure("invalid_normalized_job"))?
        && at < now - chrono::Duration::days(days)
    {
        return Ok(Some("published_before_query_window"));
    }
    let keywords = words(&explicit, "keywords")?;
    let text = automated_apply_domain::text::folded(&format!(
        "{} {}",
        item["title"].as_str().unwrap_or(""),
        item["description"].as_str().unwrap_or("")
    ));
    if !keywords.is_empty()
        && !keywords
            .iter()
            .any(|k| text.contains(&automated_apply_domain::text::folded(k)))
    {
        return Ok(Some("explicit_keyword_mismatch"));
    }
    let locations = words(&explicit, "locations")?;
    if let Some(location) = item["location"].as_str().filter(|s| !s.is_empty()) {
        let location = automated_apply_domain::text::folded(location);
        if !locations.is_empty()
            && !locations
                .iter()
                .any(|l| location.contains(&automated_apply_domain::text::folded(l)))
        {
            return Ok(Some("explicit_location_mismatch"));
        }
    }
    let employment = words(&explicit, "employment_types")?;
    if let Some(value) = item["employment_type"].as_str().filter(|s| !s.is_empty())
        && !employment.is_empty()
        && !employment.contains(&value)
    {
        return Ok(Some("explicit_employment_mismatch"));
    }
    if let Some(remote) = explicit["remote_preference"]
        .as_str()
        .filter(|s| *s != "any")
        && item["remote_type"] != "unknown"
        && item["remote_type"] != remote
    {
        return Ok(Some("explicit_remote_mismatch"));
    }
    Ok(None)
}
