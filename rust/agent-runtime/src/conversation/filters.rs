//! Filters for cached job previews. Application workers independently verify eligibility.
use super::intent::Intent;
use automated_apply_domain::text::folded;
use chrono::{DateTime, Duration, Utc};
use serde_json::Value;
use std::collections::BTreeSet;

fn strings(value: &Value) -> impl Iterator<Item = &str> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
}

pub fn matches(
    job: &Value,
    company: &Value,
    intent: &Intent,
    preferences: &Value,
    now: DateTime<Utc>,
) -> bool {
    let title = folded(job["title"].as_str().unwrap_or_default());
    let location = folded(job["location"].as_str().unwrap_or_default());
    let company_name = folded(company["name"].as_str().unwrap_or_default());
    if intent
        .company
        .as_ref()
        .is_some_and(|name| folded(name) != company_name)
        || intent.role.as_ref().is_some_and(|role| {
            folded(role)
                .split(crate::context_contract::python_space)
                .filter(|word| !word.is_empty())
                .any(|word| !title.contains(word))
        })
        || intent
            .location
            .as_ref()
            .is_some_and(|place| !location.contains(&folded(place)))
    {
        return false;
    }

    let remote_preference = preferences["remote_preference"].as_str();
    let remote_required = intent.remote || remote_preference == Some("remote");
    let remote_type = job["remote_type"].as_str();
    if remote_required && remote_type != Some("remote")
        || matches!(remote_preference, Some("onsite" | "hybrid"))
            && remote_type != remote_preference
    {
        return false;
    }
    let preferred_locations = &preferences["preferred_locations"];
    if intent.location.is_none()
        && !remote_required
        && strings(preferred_locations).next().is_some()
        && !strings(preferred_locations).any(|place| location.contains(&folded(place)))
    {
        return false;
    }
    let target_titles = &preferences["target_titles"];
    if intent.role.is_none()
        && strings(target_titles).next().is_some()
        && !strings(target_titles).any(|target| title.contains(&folded(target)))
    {
        return false;
    }
    for (key, field) in [
        ("employment_types", "employment_type"),
        ("source_platforms", "source_platform"),
    ] {
        if strings(&preferences[key]).next().is_some()
            && !strings(&preferences[key]).any(|expected| job[field] == expected)
        {
            return false;
        }
    }

    let status = job["status"].as_str();
    let application_status = preferences["application_status"].as_str();
    if matches!(status, Some("archived" | "rejected"))
        || (intent.not_applied || application_status == Some("not_applied"))
            && status == Some("applied")
        || application_status == Some("applied") && status != Some("applied")
    {
        return false;
    }
    let days = intent
        .days
        .map(i64::from)
        .or_else(|| preferences["posting_recency_days"].as_i64());
    if let Some(days) = days
        && job["date_posted"]
            .as_str()
            .and_then(|date| DateTime::parse_from_rfc3339(date).ok())
            .is_none_or(|posted| posted < now - Duration::days(days))
    {
        return false;
    }

    let skills: BTreeSet<_> = strings(&job["skills_required"]).map(folded).collect();
    let missing_skill = |skill: &str| !skills.contains(&folded(skill));
    if if intent.skills.is_empty() {
        strings(&preferences["technology_stacks"]).any(missing_skill)
    } else {
        intent.skills.iter().any(|s| missing_skill(s))
    } {
        return false;
    }
    if let Some(minimum) = preferences["relevance_threshold"].as_f64()
        && minimum > 0.0
        && job["match_score"]
            .as_f64()
            .is_none_or(|score| score < minimum)
    {
        return false;
    }
    for (field, minimum) in [("minimum_salary", true), ("maximum_salary", false)] {
        if let Some(limit) = preferences[field].as_f64() {
            let salary = job[if minimum { "salary_min" } else { "salary_max" }].as_f64();
            if salary.is_none_or(|salary| {
                if minimum {
                    salary < limit
                } else {
                    salary > limit
                }
            }) || job["salary_currency"] != preferences["salary_currency"]
                || job["salary_period"] != preferences["salary_period"]
            {
                return false;
            }
        }
    }

    let startup = &company["metadata_"]["startup_discovery"];
    let stage = startup["stage"].as_str();
    if intent.startup
        && job["source_platform"] != "work_at_a_startup"
        && !matches!(stage, Some("pre_seed" | "seed" | "early" | "startup"))
    {
        return false;
    }
    let company_stages = &preferences["company_stages"];
    if strings(company_stages).next().is_some()
        && !strings(company_stages).any(|s| Some(s) == stage)
    {
        return false;
    }
    let employees = startup["employee_count"].as_i64();
    for (field, minimum) in [("minimum_employees", true), ("maximum_employees", false)] {
        if let Some(limit) = preferences[field].as_i64()
            && employees.is_none_or(|count| {
                if minimum {
                    count < limit
                } else {
                    count > limit
                }
            })
        {
            return false;
        }
    }
    // Job rows do not carry a numeric experience requirement.
    if !preferences["minimum_experience"].is_null() || !preferences["maximum_experience"].is_null()
    {
        return false;
    }
    let searchable = format!(
        "{title} {}",
        folded(job["description"].as_str().unwrap_or_default())
    );
    !strings(&preferences["excluded_companies"]).any(|s| company_name == folded(s))
        && !strings(&preferences["excluded_titles"]).any(|s| title.contains(&folded(s)))
        && !strings(&preferences["excluded_keywords"]).any(|s| searchable.contains(&folded(s)))
}
