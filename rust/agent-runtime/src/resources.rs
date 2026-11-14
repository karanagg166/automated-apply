//! Pure saved-resource checks. Validation performs no DNS, HTTP or file reads.
use crate::{Failure, Result, profile_contract};
use chrono::{DateTime, Timelike};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::net::Ipv4Addr;
use uuid::Uuid;

pub const LINK_KINDS: &[&str] = &[
    "github",
    "linkedin",
    "portfolio",
    "resume",
    "leetcode",
    "codeforces",
    "geeksforgeeks",
    "hackerrank",
    "kaggle",
];
pub const LINK_DEFAULTS: &[(&str, &str)] = &[
    ("resume", "CANDIDATE_RESUME_DRIVE_URL"),
    ("github", "CANDIDATE_GITHUB_URL"),
    ("linkedin", "CANDIDATE_ORIGINAL_LINKEDIN_URL"),
    ("portfolio", "CANDIDATE_PORTFOLIO_URL"),
    ("leetcode", "CANDIDATE_LEETCODE_URL"),
    ("codeforces", "CANDIDATE_CODEFORCES_URL"),
    ("geeksforgeeks", "CANDIDATE_GFG_URL"),
    ("hackerrank", "CANDIDATE_HACKERRANK_URL"),
];
pub fn standard_field(kind: &str) -> Option<&'static str> {
    match kind {
        "github" => Some("github_url"),
        "linkedin" => Some("linkedin_url"),
        "portfolio" => Some("portfolio_url"),
        _ => None,
    }
}
pub fn link_defaults(values: &BTreeMap<String, String>) -> Result<BTreeMap<String, String>> {
    let mut out = BTreeMap::new();
    for (kind, key) in LINK_DEFAULTS {
        if let Some(value) = values.get(*key).filter(|s| !s.is_empty()) {
            out.insert(
                (*kind).into(),
                public_https(value).ok_or(Failure("invalid_resource_default"))?,
            );
        }
    }
    Ok(out)
}
/// Unconfirmed/ambiguous saved resources and explicitly cleared links suppress defaults.
pub fn resolved_link(
    profile: &Value,
    resources: &[Resource],
    defaults: &BTreeMap<String, String>,
    kind: &str,
) -> Value {
    let mut result = json!({"resource_type":kind,"url":null,"source":null,"resource_id":null,"user_confirmed":false});
    if let Some(field) = standard_field(kind)
        && let Some(saved) = profile[field].as_str()
    {
        result["url"] = json!(public_https(saved));
        result["source"] = json!("candidate_profile");
        result["user_confirmed"] = json!(true);
        return result;
    }
    let items: Vec<_> = resources
        .iter()
        .filter(|r| r.resource_type == kind && r.user_confirmed)
        .collect();
    let primary: Vec<_> = items.iter().copied().filter(|r| r.is_primary).collect();
    if primary.len() == 1 || items.len() == 1 {
        let item = if primary.is_empty() {
            items[0]
        } else {
            primary[0]
        };
        result["url"] = json!(public_https(&item.url));
        result["source"] = json!("candidate_resource");
        result["resource_id"] = json!(item.id);
        result["user_confirmed"] = json!(true);
        return result;
    }
    if resources.iter().any(|r| r.resource_type == kind)
        || standard_field(kind).is_some() && profile["version"].as_i64().is_some_and(|n| n > 1)
    {
        return result;
    }
    if let Some(default) = defaults.get(kind) {
        result["url"] = json!(default);
        result["source"] = json!("environment_default");
    }
    result
}

/// Python 3.11 PublicHTTPSURL compatibility. Syntax validation is not a fetch policy.
pub fn public_https(value: &str) -> Option<String> {
    let url = reqwest::Url::parse(value).ok()?;
    let host = url
        .host_str()?
        .trim_matches(['[', ']'])
        .to_ascii_lowercase();
    if url.scheme() != "https"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port_or_known_default() != Some(443)
        || !host.contains('.')
        || [".localhost", ".local", ".internal", ".localdomain"]
            .iter()
            .any(|suffix| host.ends_with(suffix))
        || url.as_str().chars().count() > 2048
    {
        return None;
    }
    if let Ok(ip) = host.parse::<Ipv4Addr>() {
        let number = u32::from(ip);
        // Frozen stdlib ipaddress 3.11 private/reserved plus shared address space.
        const BLOCKED: &[(u32, u32)] = &[
            (0x00000000, 8),
            (0x0a000000, 8),
            (0x7f000000, 8),
            (0xa9fe0000, 16),
            (0xac100000, 12),
            (0xc0000000, 24),
            (0xc00000aa, 31),
            (0xc0000200, 24),
            (0xc0a80000, 16),
            (0xc6120000, 15),
            (0xc6336400, 24),
            (0xcb007100, 24),
            (0xf0000000, 4),
            (0xffffffff, 32),
            (0x64400000, 10),
        ];
        if number != 0xc0000009
            && number != 0xc000000a
            && BLOCKED.iter().any(|(base, prefix)| {
                let mask = u32::MAX << (32 - prefix);
                number & mask == base & mask
            })
        {
            return None;
        }
    }
    if percent_encoding::percent_decode_str(url.as_str())
        .decode_utf8_lossy()
        .chars()
        .any(|c| c < '\u{20}' || c == '\\')
    {
        return None;
    }
    Some(url.into())
}

#[derive(Clone, Deserialize)]
pub struct Resource {
    pub id: Uuid,
    pub resource_type: String,
    pub label: String,
    pub url: String,
    pub user_confirmed: bool,
    pub is_primary: bool,
    pub source_type: String,
    pub updated_at: String,
}
#[derive(Clone, Serialize)]
pub struct ResumeOption {
    pub resource_id: Uuid,
    pub label: String,
    pub url: Option<String>,
    pub confirmed: bool,
    pub primary: bool,
    pub resource_version: String,
    pub download_path: Option<String>,
}
#[derive(Serialize)]
pub struct ResumeSelection {
    pub selected: Option<ResumeOption>,
    pub alternatives: Vec<ResumeOption>,
    pub reason: &'static str,
    pub upload_status: &'static str,
}
fn private_resume_id(resource: &Resource) -> Option<&str> {
    if resource.source_type != "private_upload" {
        return None;
    }
    let text = resource.url.strip_prefix("private-resume:")?;
    (text.parse::<Uuid>().ok()?.to_string() == text).then_some(text)
}
/// Python json.dumps(..., ensure_ascii=True) for the fixed string/bool resume tuple.
/// This deliberately isn't a general JSON hash (float spelling has separate rules).
pub(crate) fn ascii_string(text: &str) -> String {
    use std::fmt::Write;
    let mut out = String::from("\"");
    for unit in text.encode_utf16() {
        match unit {
            0x22 => out.push_str("\\\""),
            0x5c => out.push_str("\\\\"),
            8 => out.push_str("\\b"),
            9 => out.push_str("\\t"),
            10 => out.push_str("\\n"),
            12 => out.push_str("\\f"),
            13 => out.push_str("\\r"),
            0x20..=0x7e => out.push(char::from_u32(unit.into()).unwrap()),
            _ => write!(&mut out, "\\u{unit:04x}").unwrap(),
        }
    }
    out.push('"');
    out
}
fn version(resource: &Resource) -> Result<String> {
    let time = DateTime::parse_from_rfc3339(&resource.updated_at)
        .map_err(|_| Failure("invalid_resource_record"))?;
    let fraction = if time.nanosecond() == 0 {
        String::new()
    } else {
        format!(".{:06}", time.nanosecond() / 1000)
    };
    let timestamp = format!(
        "{}{}{}",
        time.format("%Y-%m-%d %H:%M:%S"),
        fraction,
        time.format("%:z")
    );
    let tuple = format!(
        "[{},{},{},{},{},{}]",
        ascii_string(&resource.id.to_string()),
        ascii_string(&resource.label),
        ascii_string(&resource.url),
        resource.user_confirmed,
        resource.is_primary,
        ascii_string(&timestamp)
    );
    Ok(format!("{:x}", Sha256::digest(tuple.as_bytes())))
}
pub fn select_resume(resources: &[Resource], selected_id: Option<Uuid>) -> Result<ResumeSelection> {
    let options = resources
        .iter()
        .filter(|r| r.resource_type == "resume")
        .map(|r| {
            let private = private_resume_id(r);
            Ok(ResumeOption {
                resource_id: r.id,
                label: r
                    .label
                    .trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
                    .to_owned(),
                url: if private.is_some() {
                    Some(r.url.clone())
                } else {
                    public_https(&r.url)
                },
                confirmed: r.user_confirmed,
                primary: r.is_primary,
                resource_version: version(r)?,
                download_path: private.map(|id| format!("/api/backend/dashboard/resumes/{id}")),
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let mut selected = None;
    let mut reason =
        "Choose a confirmed resume resource and mark a unique primary or select it explicitly";
    let valid = |r: &&ResumeOption| r.confirmed && (r.url.is_some() || r.download_path.is_some());
    if let Some(id) = selected_id {
        selected = options
            .iter()
            .find(|r| r.resource_id == id && valid(r))
            .cloned();
        reason = if selected.is_some() {
            "Explicit owner selection of a confirmed saved resume"
        } else {
            "Selected resume is missing, unconfirmed, invalid, or belongs to another profile"
        };
    } else {
        let primary: Vec<_> = options.iter().filter(|r| r.primary).collect();
        if primary.len() == 1 && valid(&primary[0]) {
            selected = Some(primary[0].clone());
            reason = "Unique confirmed primary resume";
        } else if primary.len() > 1 {
            reason = "Conflicting primary resumes; choose one explicitly";
        }
    }
    Ok(ResumeSelection {
        selected,
        alternatives: options,
        reason,
        upload_status: "manual_resume_upload_required",
    })
}

/// Completeness only: owner confirmation and independent PDF/identity checks stay required.
pub fn assess_profile(profile: Option<Value>, resources: &[Resource], live: bool) -> Result<Value> {
    let Some(mut profile) = profile else {
        return Ok(
            json!({"status":"blocked","profile_version":null,"missing":["candidate_profile"],"warnings":[],"resume_selected":false,"identity_independently_verified":false}),
        );
    };
    let version = profile.get("version").cloned().unwrap_or(Value::Null);
    let object = profile
        .as_object_mut()
        .ok_or(Failure("invalid_profile_record"))?;
    for key in ["version", "id", "singleton_key", "created_at", "updated_at"] {
        object.remove(key);
    }
    let facts = profile_contract::normalize_record(profile)?;
    if live {
        profile_contract::reject_placeholders(&facts)?;
        for resource in resources {
            profile_contract::reject_placeholders(
                &json!({"label":resource.label,"url":resource.url}),
            )?;
        }
    }
    let empty = |value: &Value| value.as_array().is_none_or(Vec::is_empty);
    let mut missing = Vec::new();
    for key in ["verified_skills", "projects"] {
        if empty(&facts[key]) {
            missing.push(key);
        }
    }
    if empty(&facts["verified_roles"]) && facts["verified_experience_years"].as_f64() != Some(0.0) {
        missing.push("work_history_or_explicit_zero_experience");
    }
    if facts["projects"]
        .as_array()
        .unwrap()
        .iter()
        .any(|p| p["contribution"].as_str().is_none_or(str::is_empty) || empty(&p["technologies"]))
    {
        missing.push("project_contribution_and_technologies");
    }
    if empty(&facts["preferences"]["target_titles"]) {
        missing.push("target_roles");
    }
    if empty(&facts["preferences"]["preferred_locations"])
        && facts["preferences"]["remote_preference"].is_null()
    {
        missing.push("location_or_remote_preference");
    }
    for (key, host) in [
        ("github_url", "github.com"),
        ("linkedin_url", "linkedin.com"),
    ] {
        if !facts[key]
            .as_str()
            .and_then(|s| reqwest::Url::parse(s).ok())
            .is_some_and(|url| {
                url.scheme() == "https"
                    && url
                        .host_str()
                        .is_some_and(|h| h == host || h == format!("www.{host}"))
            })
        {
            missing.push(key);
        }
    }
    if facts["portfolio_url"].is_null() && facts["personal_website"].is_null() {
        missing.push("portfolio_or_personal_website");
    }
    let selected = select_resume(resources, None)?.selected.is_some();
    if !selected {
        missing.push("confirmed_unique_primary_resume");
    }
    Ok(
        json!({"status":if missing.is_empty() {"owner_confirmation_required"} else {"blocked"},"profile_version":version,"missing":missing,"warnings":["Profile facts and links require owner confirmation; no sites or resume bytes were fetched","Salary, education and work authorization remain unknown unless explicitly supplied"],"resume_selected":selected,"identity_independently_verified":false}),
    )
}
