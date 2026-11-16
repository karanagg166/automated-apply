//! Compare saved canonical facts with observed portal fields. Only separately approved
//! summary/skill updates are supported; comparisons confer no save authority.
use crate::{Failure, Result, context_contract::python_space};
use automated_apply_domain::text::{folded, skill_key};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, sync::LazyLock};
pub const FIELDS: &[&str] = &[
    "full_name",
    "email",
    "phone",
    "summary",
    "skills",
    "experience",
    "education",
    "projects",
    "location",
    "preferences",
    "notice_period",
    "expected_compensation",
    "resume",
    "github",
    "portfolio",
    "linkedin",
    "headline",
    "professional_title",
];
pub const WRITABLE: &[&str] = &["summary", "skills"];
fn collapse(value: &str) -> String {
    value
        .split(python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
pub fn reference(value: &Value) -> Option<String> {
    if value.is_null() || value == "" || value == &json!([]) || value == &json!({}) {
        None
    } else {
        Some(format!(
            "{:x}",
            Sha256::digest(crate::python_json::serialize(value, true, false).as_bytes())
        ))
    }
}
pub fn comparison_value(field: &str, value: &Value) -> Value {
    if field == "full_name"
        && let Some(value) = value.as_str()
    {
        return json!(folded(&collapse(value)));
    }
    if field == "skills"
        && let Some(values) = value.as_array()
        && values.iter().all(Value::is_string)
    {
        return json!(
            values
                .iter()
                .map(|v| folded(&collapse(v.as_str().unwrap())))
                .collect::<BTreeSet<_>>()
        );
    }
    if field == "phone"
        && let Some(value) = value.as_str()
    {
        static DECIMAL: LazyLock<regex::Regex> =
            LazyLock::new(|| regex::Regex::new(r"\p{Nd}").expect("Unicode decimal digit"));
        return json!(
            DECIMAL
                .find_iter(value)
                .map(|m| m.as_str())
                .collect::<String>()
        );
    }
    value.clone()
}
pub fn skills(value: &Value, empty: bool) -> Result<Vec<String>> {
    let values = value
        .as_array()
        .filter(|v| v.len() <= 100 && (empty || !v.is_empty()))
        .ok_or(Failure("profile_skills_bounded_observation_required"))?;
    values
        .iter()
        .map(|value| {
            let raw = value
                .as_str()
                .filter(|v| v.chars().count() <= 200 && !v.trim_matches(python_space).is_empty())
                .ok_or(Failure("profile_skills_bounded_observation_required"))?;
            Ok(collapse(raw))
        })
        .collect()
}
pub fn additions(canonical: &Value, existing: &Value) -> Result<Vec<String>> {
    let mut before = skills(existing, true)?
        .iter()
        .map(|s| skill_key(s))
        .collect::<BTreeSet<_>>();
    let mut result = vec![];
    for item in skills(canonical, false)? {
        if before.insert(skill_key(&item)) {
            result.push(item);
        }
    }
    Ok(result)
}
pub fn prepared(before: &Value, approved: &Value, observed: &Value) -> Result<Vec<String>> {
    let before = skills(before, true)?;
    let observed = skills(observed, false)?;
    if !observed.starts_with(&before) || observed.len() <= before.len() {
        return Err(Failure(
            "profile_skills_existing_chips_changed_or_no_addition",
        ));
    }
    let approved = skills(approved, false)?
        .iter()
        .map(|s| folded(s))
        .collect::<BTreeSet<_>>();
    let added = &observed[before.len()..];
    if added.iter().any(|s| !approved.contains(&folded(s)))
        || observed
            .iter()
            .map(|s| skill_key(s))
            .collect::<BTreeSet<_>>()
            .len()
            != before
                .iter()
                .map(|s| skill_key(s))
                .collect::<BTreeSet<_>>()
                .len()
                + added.len()
    {
        return Err(Failure("profile_skills_unapproved_or_duplicate_addition"));
    }
    Ok(observed)
}
pub fn canonical(profile: &Value, resume_version: Option<&str>) -> Value {
    let preferences = &profile["preferences"];
    let mut selected = json!({});
    for key in ["preferred_locations", "remote_preference"] {
        if let Some(value) = preferences.get(key) {
            selected[key] = value.clone();
        }
    }
    json!({"full_name":profile["full_name"],"email":profile["email"],"phone":profile["phone"],"summary":profile["summary"],"skills":profile["verified_skills"],"experience":profile["verified_roles"],"education":profile["education"],"projects":profile["projects"],"location":preferences["current_location"],"preferences":selected,"notice_period":preferences["notice_period_days"],"expected_compensation":preferences["expected_compensation"],"resume":resume_version,"github":profile["github_url"],"portfolio":profile["portfolio_url"],"linkedin":profile["linkedin_url"],"headline":null,"professional_title":null})
}
pub fn compare(canonical: &Value, observed: &Value, approved: &[String]) -> Result<Vec<Value>> {
    if !canonical.is_object() || !observed.is_object() {
        return Err(Failure("invalid_execution_saved_record"));
    }
    let mut result = vec![];
    for name in FIELDS {
        let name = *name;
        let expected = comparison_value(name, &canonical[name]);
        let reported = comparison_value(name, &observed[name]);
        let desired = reference(&expected);
        let actual = reference(&reported);
        let is_approved = approved.iter().any(|s| s == name);
        let national = if name == "phone" {
            expected
                .as_str()
                .zip(reported.as_str())
                .is_some_and(|(e, r)| {
                    let e_len = e.chars().count();
                    let r_len = r.chars().count();
                    r_len >= 7
                        && r_len < e_len
                        && e_len <= r_len + 3
                        && e.ends_with(r)
                        && canonical[name].as_str().is_some_and(|s| s.starts_with('+'))
                        && observed[name].as_str().is_none_or(|s| !s.starts_with('+'))
                })
        } else {
            false
        };
        let state = if observed.get(name).is_none() {
            "UNSUPPORTED"
        } else if national {
            "PRESENT_DETAILS_UNVERIFIED"
        } else if matches!(name, "education" | "experience" | "projects")
            && reported == json!({"presence_only":true})
        {
            if desired.is_some() {
                "PRESENT_DETAILS_UNVERIFIED"
            } else {
                "MISSING_FROM_DATABASE"
            }
        } else if desired.is_none()
            && actual.is_none()
            && matches!(
                name,
                "full_name" | "phone" | "summary" | "skills" | "experience" | "education"
            )
        {
            "MISSING_INFORMATION"
        } else if desired.is_none() && actual.is_some() {
            "MISSING_FROM_DATABASE"
        } else if desired == actual {
            "MATCHED"
        } else if desired.is_some() && actual.is_none() {
            "MISSING_FROM_PLATFORM"
        } else if is_approved {
            "OUTDATED"
        } else {
            "CONFLICT"
        };
        let addable = if name == "skills" && desired.is_some() && reported.is_array() {
            !additions(&canonical[name], &observed[name])?.is_empty()
        } else {
            true
        };
        let supported = WRITABLE.contains(&name);
        result.push(json!({"field":name,"state":state,"previous_reference":actual,"new_reference":desired,"update_supported":supported,"may_update":desired.is_some() && addable && is_approved && supported && matches!(state,"OUTDATED"|"MISSING_FROM_PLATFORM")}));
    }
    Ok(result)
}
