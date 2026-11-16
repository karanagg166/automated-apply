//! Read-only queue observations; URL hints never establish eligibility or authorize Apply.
use crate::{Failure, Result};
use chrono::{DateTime, NaiveDate, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::sync::LazyLock;
use uuid::Uuid;

pub const TERMINAL: &[&str] = &[
    "SUBMITTED_RECORDED",
    "SUBMITTED_CONFIRMED",
    "FAILED_FINAL",
    "SKIPPED",
];
pub const WRITES: &[&str] = &["apply", "answer", "upload_resume", "answer_questionnaire"];
pub const FILTER_HOLDS: &[&str] = &[
    "posting_outside_age_limit",
    "posting_age_requires_review",
    "posting_timestamp_unknown",
    "applicant_limit_reached",
    "applicant_count_unknown_skip",
    "applicant_count_requires_review",
    "required_experience_outside_verified_band",
    "verified_experience_requirements_required",
    "current_profile_preferences_or_required_skills_exclude_job",
    "minimum_match_score_required",
    "advertised_experience_outside_platform_preferences",
    "advertised_salary_outside_platform_preferences",
    "salary_comparison_requires_review",
    "uncertain_job_requirements_require_review",
    "verified_profile_context_changed",
];
fn truth(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
        Value::Number(n) => n.as_f64() != Some(0.0),
    }
}
pub fn uses_capacity(value: &Value) -> bool {
    if value["stage"]
        .as_str()
        .is_some_and(|s| TERMINAL.contains(&s))
    {
        return false;
    }
    !(value["stage"] == "NEEDS_INPUT"
        && value["status"] == "waiting"
        && value["reason"]
            .as_str()
            .is_some_and(|s| FILTER_HOLDS.contains(&s))
        && value["admitted_actions"] == json!([])
        && !["packet_id", "form_pending", "lease_until"]
            .iter()
            .any(|k| truth(&value[k])))
}
fn integer(v: &Value) -> Option<i128> {
    v.as_i64()
        .map(i128::from)
        .or_else(|| v.as_u64().map(i128::from))
}
pub fn listing_exclusion(
    facts: &Value,
    effective: &Value,
    now: DateTime<Utc>,
) -> Result<Option<&'static str>> {
    let age = effective["max_job_age_days"]
        .as_i64()
        .filter(|n| (1..=30).contains(n))
        .ok_or(Failure("invalid_execution_contract"))?;
    let duration = chrono::Duration::days(age);
    let posted = if truth(&facts["posted_at"]) {
        match facts["posted_at"]
            .as_str()
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        {
            Some(d) => d.with_timezone(&Utc),
            None => return Ok(Some("posting_timestamp_unknown")),
        }
    } else if truth(&facts["posted_date"]) {
        let day = match facts["posted_date"]
            .as_str()
            .and_then(|s| NaiveDate::parse_from_str(s, "%Y-%m-%d").ok())
        {
            Some(day) => day,
            None => return Ok(Some("posting_timestamp_unknown")),
        };
        let earliest = day
            .and_hms_opt(0, 0, 0)
            .ok_or(Failure("invalid_execution_contract"))?
            .and_utc()
            - chrono::Duration::hours(14);
        let latest = earliest + chrono::Duration::hours(50);
        if now < earliest {
            return Ok(Some("posting_outside_age_limit"));
        }
        if now - earliest > duration {
            return Ok(Some(if now - latest > duration {
                "posting_outside_age_limit"
            } else {
                "posting_age_requires_review"
            }));
        }
        earliest
    } else {
        return Ok(Some("posting_timestamp_unknown"));
    };
    if now < posted || now - posted > duration {
        return Ok(Some("posting_outside_age_limit"));
    }
    if effective["applicant_limit"].is_null() {
        return Ok(None);
    }
    let threshold = integer(&effective["applicant_limit"])
        .filter(|n| *n > 0)
        .ok_or(Failure("invalid_execution_contract"))?;
    let lo = integer(&facts["applicants_min"]);
    let hi = integer(&facts["applicants_max"]);
    if !facts["applicants_min"].is_null() && lo.is_none_or(|n| n < 0)
        || !facts["applicants_max"].is_null() && hi.is_none_or(|n| n < 0)
        || lo.zip(hi).is_some_and(|(lo, hi)| lo > hi)
    {
        return Ok(Some("invalid_applicant_bounds"));
    }
    if lo.is_some_and(|n| n >= threshold) {
        return Ok(Some("applicant_limit_reached"));
    }
    if hi.is_some_and(|n| n >= 0 && n < threshold) {
        return Ok(None);
    }
    Ok(match effective["unknown_applicants"].as_str() {
        Some("allow_lower_bound") => {
            if lo.is_some() && hi.is_none() {
                None
            } else {
                Some("applicant_count_requires_review")
            }
        }
        Some("skip") => Some("applicant_count_unknown_skip"),
        Some("needs_review") => Some("applicant_count_requires_review"),
        Some("allow") => None,
        _ => return Err(Failure("invalid_execution_contract")),
    })
}
pub fn naukri_url(raw: &str) -> Result<String> {
    static PATH: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"^/job-listings-[a-zA-Z0-9%_-]+-[0-9]{10,20}/?$")
            .expect("fixed Naukri posting path")
    });
    let safe =
        crate::resources::public_https(raw).ok_or(Failure("public_https_job_url_required"))?;
    let url = reqwest::Url::parse(&safe).map_err(|_| Failure("public_https_job_url_required"))?;
    if !matches!(url.host_str(), Some("naukri.com" | "www.naukri.com")) {
        return Err(Failure("naukri_job_url_required"));
    }
    if !PATH.is_match(url.path()) {
        return Err(Failure("naukri_posting_path_required"));
    }
    Ok(format!(
        "https://www.naukri.com{}",
        url.path().trim_end_matches('/')
    ))
}
pub fn initial_item(
    config: &Value,
    url: &str,
    source: &str,
    reference: Option<&str>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let url = naukri_url(url)?;
    let requisition = url
        .rsplit('-')
        .next()
        .ok_or(Failure("naukri_posting_path_required"))?;
    let id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("naukri:{requisition}").as_bytes(),
    );
    let stamp = now.to_rfc3339();
    Ok(
        json!({"id":id,"platform":"naukri","requisition":requisition,"url":url,"source":source,"source_reference_hash":reference.filter(|s|!s.is_empty()).map(|s|format!("{:x}",Sha256::digest(s.as_bytes()))),"stage":"DISCOVERED","status":"queued","operation":"inspect_job","revision":1,"policy_revision":config["revision"],"job_id":null,"packet_id":null,"title":null,"company":null,"location":null,"facts":{},"match_score":null,"attempts":0,"created_at":stamp,"updated_at":stamp,"available_at":stamp,"lease_until":null,"lease_token":null,"binding":null,"reason":null,"admitted_actions":[]}),
    )
}
pub fn inspection_order(
    value: &Value,
    created: DateTime<Utc>,
    years: Option<f64>,
    now: DateTime<Utc>,
) -> u8 {
    if value["operation"] != "inspect_job" {
        return 0;
    }
    if created <= now - chrono::Duration::hours(2) {
        return 1;
    }
    let Some(years) = years else {
        return 3;
    };
    static BAND: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"-([0-9]+)-to-([0-9]+)-years?-[0-9]{12}$")
            .expect("fixed experience hint")
    });
    if let Some(url) = value["url"]
        .as_str()
        .and_then(|s| reqwest::Url::parse(s).ok())
        && let Some(caps) = BAND.captures(url.path())
        && let (Ok(lo), Ok(hi)) = (caps[1].parse::<f64>(), caps[2].parse::<f64>())
        && lo <= years
        && years <= hi
    {
        return 2;
    }
    3
}
