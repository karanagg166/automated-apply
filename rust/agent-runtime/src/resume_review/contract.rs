use super::*;
use crate::{profile_contract, resource_contract};
use automated_apply_domain::text::folded;
use std::collections::BTreeSet;
pub struct SourceInput {
    pub canonical_url: String,
    pub file_id: String,
    pub expected: i32,
    pub enabled: bool,
    pub interval: i32,
}
pub struct Approval {
    pub expected: i32,
    pub expected_profile: Option<i32>,
    pub expected_primary: Option<Uuid>,
    pub expected_sha256: Option<String>,
    pub profile: Value,
    pub evidence: Vec<Value>,
    pub allow_removals: bool,
}
fn integer(raw: Value, minimum: i64, maximum: i64) -> Result<i32> {
    profile_contract::pagination_integer(raw, minimum, maximum)
        .map(|n| n as i32)
        .map_err(|_| invalid())
}
fn boolean(raw: Option<&Value>, default: bool) -> Result<bool> {
    match raw {
        None => Ok(default),
        Some(raw) => resource_contract::boolean(raw)
            .map_err(|_| invalid())?
            .as_bool()
            .ok_or_else(invalid),
    }
}
pub fn canonical_source(raw: &str, expected: Option<&str>) -> Result<(String, String)> {
    let error = Failure("invalid_resume_drive_source");
    if raw.len() > 2048 || !raw.is_ascii() || raw.bytes().any(|c| c <= 32) {
        return Err(error);
    }
    let (scheme, rest) = raw.split_once("://").ok_or(error)?;
    let (authority, path) = rest.split_once('/').ok_or(error)?;
    if !scheme.eq_ignore_ascii_case("https") || authority != "drive.google.com" {
        return Err(error);
    }
    let url = reqwest::Url::parse(raw).map_err(|_| error)?;
    if url.fragment().is_some_and(|s| !s.is_empty()) {
        return Err(error);
    }
    let path = path.split(['?', '#']).next().ok_or(error)?;
    let file_id = path
        .strip_prefix("file/d/")
        .and_then(|s| s.strip_suffix("/view"))
        .ok_or(error)?;
    if !(10..=200).contains(&file_id.len())
        || !file_id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        || expected.is_some_and(|id| id != file_id)
    {
        return Err(error);
    }
    if let Some(query) = url.query().filter(|s| !s.is_empty()) {
        if query.split('&').any(|pair| !pair.contains('=')) {
            return Err(error);
        }
        let pairs = url.query_pairs().collect::<Vec<_>>();
        if pairs.len() > 1 || pairs.iter().any(|(key, _)| key != "usp") {
            return Err(error);
        }
    }
    Ok((
        file_id.into(),
        format!("https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"),
    ))
}
pub fn source_request(raw: Value) -> Result<SourceInput> {
    let object = raw.as_object().ok_or_else(invalid)?;
    if object.keys().any(|key| {
        !matches!(
            key.as_str(),
            "canonical_url" | "expected_generation" | "sync_enabled" | "interval_hours"
        )
    }) {
        return Err(invalid());
    }
    let (file_id, canonical_url) = canonical_source(
        raw["canonical_url"]
            .as_str()
            .ok_or_else(invalid)?
            .trim_matches(crate::context_contract::python_space),
        None,
    )?;
    Ok(SourceInput {
        canonical_url,
        file_id,
        expected: integer(raw["expected_generation"].clone(), 1, i32::MAX as i64 - 1)?,
        enabled: boolean(raw.get("sync_enabled"), false)?,
        interval: integer(
            raw.get("interval_hours").cloned().unwrap_or(json!(24)),
            1,
            168,
        )?,
    })
}
pub fn approval_request(raw: Value) -> Result<Approval> {
    let object = raw.as_object().ok_or_else(invalid)?;
    if object.keys().any(|key| {
        !matches!(
            key.as_str(),
            "owner_confirmed"
                | "primary"
                | "expected_primary_resource_id"
                | "expected_sha256"
                | "expected_profile_version"
                | "expected_generation"
                | "profile"
                | "allow_skill_removals"
                | "evidence"
        )
    }) || raw["owner_confirmed"] != true
    {
        return Err(invalid());
    }
    if let Some(value) = raw.get("primary") {
        boolean(Some(value), false)?;
    }
    let expected_profile = raw
        .get("expected_profile_version")
        .filter(|v| !v.is_null())
        .map(|v| integer(v.clone(), 1, i32::MAX as i64 - 1))
        .transpose()?;
    let expected_primary = raw
        .get("expected_primary_resource_id")
        .filter(|v| !v.is_null())
        .map(|v| {
            v.as_str()
                .ok_or_else(invalid)?
                .parse::<Uuid>()
                .map_err(|_| invalid())
        })
        .transpose()?;
    let sha = raw
        .get("expected_sha256")
        .filter(|v| !v.is_null())
        .map(|v| {
            v.as_str()
                .filter(|s| {
                    s.len() == 64
                        && s.bytes()
                            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
                })
                .map(str::to_owned)
                .ok_or_else(invalid)
        })
        .transpose()?;
    let evidence = raw
        .get("evidence")
        .map(|v| v.as_array().ok_or_else(invalid))
        .transpose()?
        .cloned()
        .unwrap_or_default();
    if evidence.len() > 20 {
        return Err(invalid());
    }
    let evidence = evidence
        .into_iter()
        .map(|item| {
            let item = resource_contract::normalize(resource_contract::Operation::Evidence, item)
                .map_err(|_| invalid())?;
            if item["user_confirmed"] != true {
                return Err(invalid());
            }
            Ok(item)
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(Approval {
        expected: integer(raw["expected_generation"].clone(), 1, i32::MAX as i64 - 1)?,
        expected_profile,
        expected_primary,
        expected_sha256: sha,
        profile: profile_contract::normalize(
            profile_contract::Operation::Create,
            raw["profile"].clone(),
        )
        .map_err(|_| invalid())?,
        evidence,
        allow_removals: boolean(raw.get("allow_skill_removals"), false)?,
    })
}
const CATEGORIES: &[&str] = &[
    "skills",
    "work_experience",
    "employment_dates",
    "education",
    "projects",
    "professional_links",
    "achievements",
    "other_claims",
];
fn string(value: &Value) -> Result<String> {
    match value {
        Value::String(s) => Ok(s.clone()),
        Value::Number(_) => Ok(crate::python_json::serialize(value, true, false)),
        Value::Bool(v) => Ok(if *v { "True" } else { "False" }.into()),
        Value::Null => Ok("None".into()),
        _ => Err(Failure("invalid_resume_review_record")),
    }
}
fn truth(value: &Value) -> bool {
    !value.is_null()
        && value != false
        && value != 0
        && value != ""
        && value != &json!([])
        && value != &json!({})
}
fn describe(item: &Value, fields: &[&str]) -> Result<String> {
    fields
        .iter()
        .filter_map(|field| item.get(*field))
        .filter(|v| truth(v))
        .map(string)
        .collect::<Result<Vec<_>>>()
        .map(|values| values.join(" · ").chars().take(2000).collect())
}
fn list(value: Option<&Value>) -> Result<Vec<Value>> {
    value
        .map(|v| {
            v.as_array()
                .cloned()
                .ok_or(Failure("invalid_resume_review_record"))
        })
        .transpose()
        .map(|v| v.unwrap_or_default())
}
pub fn differences(
    previous: &Value,
    current: &Value,
    skills: &Value,
    profile: &Value,
) -> Result<Value> {
    let mut verified = json!({});
    verified["skills"] = skills.clone();
    for (category, key, fields) in [
        (
            "work_experience",
            "verified_roles",
            vec!["company", "role", "highlight"],
        ),
        (
            "employment_dates",
            "verified_roles",
            vec!["company", "role", "start_date", "end_date"],
        ),
        (
            "education",
            "education",
            vec![
                "institution",
                "qualification",
                "field_of_study",
                "graduation_year",
            ],
        ),
        (
            "projects",
            "projects",
            vec!["name", "description", "contribution", "measurable_results"],
        ),
    ] {
        verified[category] = json!(
            list(profile.get(key))?
                .iter()
                .map(|item| describe(item, &fields))
                .collect::<Result<Vec<_>>>()?
        );
    }
    verified["professional_links"] = json!(
        [
            "github_url",
            "linkedin_url",
            "portfolio_url",
            "personal_website"
        ]
        .iter()
        .filter_map(|key| profile.get(*key))
        .filter(|v| truth(v))
        .map(string)
        .collect::<Result<Vec<_>>>()?
    );
    let mut achievements = vec![];
    for project in list(profile.get("projects"))? {
        achievements.extend(list(project.get("achievements"))?);
    }
    for item in list(profile.get("certifications"))? {
        achievements.push(json!(describe(&item, &["name", "issuer", "issued_on"])?));
    }
    verified["achievements"] = json!(achievements);
    verified["other_claims"] = json!(
        [
            "full_name",
            "email",
            "phone",
            "summary",
            "verified_experience_years"
        ]
        .iter()
        .filter_map(|key| profile.get(*key))
        .filter(|v| !v.is_null())
        .map(string)
        .collect::<Result<Vec<_>>>()?
    );
    let mut changes = vec![];
    for category in CATEGORIES {
        let before = if *category == "skills" {
            previous["suggestions"]
                .get("verified_skills")
                .unwrap_or(skills)
                .clone()
        } else {
            previous["sections"]
                .get(*category)
                .cloned()
                .unwrap_or(json!([]))
        };
        let after = if *category == "skills" {
            current["suggestions"]["verified_skills"].clone()
        } else {
            current["sections"][*category].clone()
        };
        let before_values = before
            .as_array()
            .ok_or(Failure("invalid_resume_review_record"))?;
        let after_values = after
            .as_array()
            .ok_or(Failure("invalid_resume_review_record"))?;
        let words = |values: &Vec<Value>| -> Result<BTreeSet<String>> {
            values
                .iter()
                .map(|v| {
                    v.as_str()
                        .map(folded)
                        .ok_or(Failure("invalid_resume_review_record"))
                })
                .collect()
        };
        let old = words(before_values)?;
        let new = words(after_values)?;
        let added = after_values
            .iter()
            .filter(|v| !old.contains(&folded(v.as_str().unwrap())))
            .cloned()
            .collect::<Vec<_>>();
        let removed = before_values
            .iter()
            .filter(|v| !new.contains(&folded(v.as_str().unwrap())))
            .cloned()
            .collect::<Vec<_>>();
        changes.push(json!({"category":category,"before":before,"after":after,"current_verified":verified[*category],"added":added,"removed":removed}));
    }
    Ok(json!(changes))
}
