//! Factual saved-listing decisions shared by preparation, admission and reconsideration.
//! Matching never creates a claim or browser authority.
use super::{contracts, filters};
use crate::{Failure, Result, job_context::Reviewed};
use automated_apply_domain::matching::{self, Company, Listing, Profile};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};

fn invalid() -> Failure {
    Failure("invalid_execution_saved_record")
}
fn optional_number(value: &Value) -> Result<Option<f64>> {
    if value.is_null() {
        Ok(None)
    } else {
        value
            .as_f64()
            .filter(|n| n.is_finite())
            .map(Some)
            .ok_or_else(invalid)
    }
}
pub fn hold(value: &mut Value, reason: &str) {
    let excluded = matches!(
        reason,
        "posting_outside_age_limit"
            | "applicant_limit_reached"
            | "applicant_count_unknown_skip"
            | "prior_application_or_unknown_submission_no_replay"
            | "required_experience_outside_verified_band"
            | "current_profile_preferences_or_required_skills_exclude_job"
            | "minimum_match_score_required"
            | "advertised_experience_outside_platform_preferences"
            | "advertised_salary_outside_platform_preferences"
            | "vacancy_closed_expired_or_invalid"
    );
    value["stage"] = json!(if excluded { "SKIPPED" } else { "NEEDS_INPUT" });
    value["status"] = json!(if excluded { "complete" } else { "waiting" });
    value["reason"] = json!(reason);
}
pub fn check(
    work: &mut Value,
    policy: &Value,
    job: Value,
    company: Option<Value>,
    profile: &Value,
    now: DateTime<Utc>,
) -> Result<()> {
    if crate::packet_platform::posting_unavailable(&job, now.date_naive())? {
        return Err(Failure("vacancy_closed_expired_or_invalid"));
    }
    let metadata = job["discovery_metadata"].clone();
    let reviewed = Reviewed::new(job, company)?;
    let mut view = reviewed.job_view().clone();
    if metadata["source_name"] == "naukri" {
        view["is_remote"] = json!(view["remote_type"] == "remote");
        view["date_posted"] = if crate::packet_context::date_present(&metadata["date_posted"]) {
            metadata["date_posted"].clone()
        } else {
            Value::Null
        };
    }
    for key in ["salary_min", "salary_max"] {
        if let Some(text) = view[key].as_str() {
            view[key] = json!(
                text.parse::<f64>()
                    .ok()
                    .filter(|n| n.is_finite())
                    .ok_or_else(invalid)?
            );
        }
    }
    if view["skills_required"].is_null() {
        view["skills_required"] = json!([]);
    }
    if view["remote_type"].is_null() || view["remote_type"] == "" {
        view["remote_type"] = json!("unknown");
    }
    let listing: Listing = serde_json::from_value(view.clone()).map_err(|_| invalid())?;
    let mut candidate: Profile = serde_json::from_value(profile.clone()).map_err(|_| invalid())?;
    let platform = work["platform"].as_str().ok_or_else(invalid)?;
    let setting = &policy["platforms"][platform];
    if setting["preferences_mode"] == "custom" {
        let preferences = &setting["preferences"];
        candidate.preferences.target_titles =
            serde_json::from_value(preferences["roles"].clone()).map_err(|_| invalid())?;
        candidate.preferences.preferred_locations =
            serde_json::from_value(preferences["locations"].clone()).map_err(|_| invalid())?;
        candidate.preferences.minimum_salary = optional_number(&preferences["minimum_salary"])?;
        candidate.preferences.salary_currency = Some(
            preferences["salary_currency"]
                .as_str()
                .ok_or_else(invalid)?
                .to_owned(),
        );
        candidate.preferences.salary_period = Some(
            preferences["salary_period"]
                .as_str()
                .ok_or_else(invalid)?
                .to_owned(),
        );
        for name in preferences["excluded_companies"]
            .as_array()
            .ok_or_else(invalid)?
        {
            let name = name.as_str().ok_or_else(invalid)?.to_owned();
            if !candidate.preferences.excluded_companies.contains(&name) {
                candidate.preferences.excluded_companies.push(name);
            }
        }
        let lower = optional_number(&metadata["experience_min_years"])?;
        let upper = optional_number(&metadata["experience_max_years"])?;
        if optional_number(&preferences["experience_min"])?
            .is_some_and(|n| lower.is_none_or(|l| l < n))
            || optional_number(&preferences["experience_max"])?
                .is_some_and(|n| upper.is_none_or(|u| u > n))
        {
            return Err(Failure(
                "advertised_experience_outside_platform_preferences",
            ));
        }
        if let Some(maximum) = optional_number(&preferences["maximum_salary"])? {
            if listing.salary_min.is_none()
                || listing.salary_max.is_none()
                || view["salary_currency"] != preferences["salary_currency"]
                || view["salary_period"] != preferences["salary_period"]
            {
                return Err(Failure("salary_comparison_requires_review"));
            }
            if listing.salary_max.is_some_and(|n| n > maximum) {
                return Err(Failure("advertised_salary_outside_platform_preferences"));
            }
        }
    }
    let lower = optional_number(&metadata["experience_min_years"])?;
    let upper = optional_number(&metadata["experience_max_years"])?;
    let Some((lower, years)) = lower.zip(candidate.verified_experience_years) else {
        return Err(Failure("verified_experience_requirements_required"));
    };
    if years < lower || upper.is_some_and(|n| years > n) {
        return Err(Failure("required_experience_outside_verified_band"));
    }
    let company=reviewed.employer().map(|c|{let data=&c["metadata_"]["startup_discovery"];serde_json::from_value::<Company>(json!({"name":c["name"],"domain":c["domain"],"startup_stage":data["stage"],"startup_source":data["source"]})).map_err(|_|invalid())}).transpose()?;
    let matched = matching::discovery_match(&listing, &candidate, company.as_ref(), false);
    let limits = contracts::limits(policy, platform)?;
    if let Some(reason) = filters::listing_exclusion(&work["facts"], &limits, now)? {
        return Err(Failure(reason));
    }
    work["match_score"] = json!(matched.match_score);
    let any = setting["skill_match_mode"] == "any";
    let blocked = matched
        .negative_factors
        .iter()
        .any(|factor| !(any && factor == "Some required skills are not in the saved profile"));
    if !matched.exclusion_reasons.is_empty()
        || blocked
        || matched.matched_skills.is_empty()
        || !any && !matched.missing_skills.is_empty()
    {
        return Err(Failure(
            "current_profile_preferences_or_required_skills_exclude_job",
        ));
    }
    if matched.match_score < limits["minimum_match_score"].as_f64().ok_or_else(invalid)? {
        return Err(Failure("minimum_match_score_required"));
    }
    let remote_any = candidate
        .preferences
        .remote_preference
        .as_deref()
        .is_none_or(|s| s == "any");
    let date = work["facts"]["posted_date"]
        .as_str()
        .is_some_and(|s| !s.is_empty());
    if matched.unknown_fields.iter().any(|field| {
        !matches!(
            field.as_str(),
            "company_size" | "salary" | "experience_suitability"
        ) && !(remote_any && field == "remote_policy")
            && !(date && field == "publication_date")
    }) {
        return Err(Failure("uncertain_job_requirements_require_review"));
    }
    Ok(())
}
