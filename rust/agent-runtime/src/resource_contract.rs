//! Explicit resource/evidence contracts; writes never accept private-upload authority.
use crate::{Failure, Result, profile_contract, resources::public_https};
use serde_json::{Map, Value, json};
use uuid::Uuid;
#[derive(Clone, Copy)]
pub enum Operation {
    Resource,
    Evidence,
    Patch,
}
fn invalid() -> Failure {
    Failure("invalid_resource_input")
}
fn strip(value: &str) -> &str {
    value.trim()
}
fn text(value: &Value, max: usize) -> Result<Value> {
    let text = strip(value.as_str().ok_or_else(invalid)?);
    if text.is_empty() || text.chars().count() > max {
        return Err(invalid());
    }
    Ok(json!(text))
}
pub(crate) fn boolean(value: &Value) -> Result<Value> {
    match value {
        Value::Bool(_) => Ok(value.clone()),
        Value::Number(n) if n.as_f64() == Some(0.0) => Ok(json!(false)),
        Value::Number(n) if n.as_f64() == Some(1.0) => Ok(json!(true)),
        Value::String(s) => match s.to_ascii_lowercase().as_str() {
            "0" | "off" | "f" | "false" | "n" | "no" => Ok(json!(false)),
            "1" | "on" | "t" | "true" | "y" | "yes" => Ok(json!(true)),
            _ => Err(invalid()),
        },
        _ => Err(invalid()),
    }
}
pub fn normalize(operation: Operation, input: Value) -> Result<Value> {
    let input = input.as_object().ok_or_else(invalid)?;
    let (allowed, required): (&[&str], &[&str]) = match operation {
        Operation::Resource => (
            &[
                "id",
                "resource_type",
                "label",
                "url",
                "is_primary",
                "source_type",
                "user_confirmed",
                "expected_profile_version",
            ],
            &["resource_type", "label", "url"],
        ),
        Operation::Evidence => (
            &[
                "evidence_type",
                "title",
                "content",
                "source_url",
                "source_description",
                "user_confirmed",
                "project",
            ],
            &["evidence_type", "title", "content"],
        ),
        Operation::Patch => (
            &[
                "title",
                "content",
                "source_url",
                "source_description",
                "user_confirmed",
                "project",
            ],
            &[],
        ),
    };
    if input.keys().any(|k| !allowed.contains(&k.as_str()))
        || required.iter().any(|k| !input.contains_key(*k))
        || matches!(operation, Operation::Patch) && input.is_empty()
    {
        return Err(invalid());
    }
    let mut out = Map::new();
    for (key, value) in input {
        let nullable = matches!(
            key.as_str(),
            "id" | "expected_profile_version" | "source_url" | "source_description" | "project"
        );
        let normalized = if nullable && value.is_null() {
            Value::Null
        } else {
            match key.as_str() {
                "resource_type" => {
                    if ![
                        "resume",
                        "github",
                        "linkedin",
                        "portfolio",
                        "leetcode",
                        "codeforces",
                        "geeksforgeeks",
                        "hackerrank",
                        "kaggle",
                        "other",
                    ]
                    .contains(&value.as_str().ok_or_else(invalid)?)
                    {
                        return Err(invalid());
                    }
                    value.clone()
                }
                "evidence_type" => {
                    if ![
                        "project",
                        "experience",
                        "achievement",
                        "resume_note",
                        "other",
                    ]
                    .contains(&value.as_str().ok_or_else(invalid)?)
                    {
                        return Err(invalid());
                    }
                    value.clone()
                }
                "source_type" => {
                    if !["user", "environment_import"]
                        .contains(&value.as_str().ok_or_else(invalid)?)
                    {
                        return Err(invalid());
                    }
                    value.clone()
                }
                "label" | "title" | "source_description" => text(value, 200)?,
                "content" => text(value, 4000)?,
                "url" | "source_url" => {
                    json!(public_https(value.as_str().ok_or_else(invalid)?).ok_or_else(invalid)?)
                }
                "id" => json!(
                    value
                        .as_str()
                        .and_then(|s| s.parse::<Uuid>().ok())
                        .ok_or_else(invalid)?
                        .to_string()
                ),
                "is_primary" | "user_confirmed" => boolean(value)?,
                "expected_profile_version" => {
                    profile_contract::resource_version(value.clone()).map_err(|_| invalid())?
                }
                "project" => {
                    let mut project =
                        profile_contract::project(value.clone()).map_err(|_| invalid())?;
                    if matches!(operation, Operation::Patch) {
                        project
                            .as_object_mut()
                            .unwrap()
                            .retain(|key, _| value.get(key).is_some());
                    }
                    project
                }
                _ => return Err(invalid()),
            }
        };
        out.insert(key.clone(), normalized);
    }
    let defaults: &[(&str, Value)] = match operation {
        Operation::Resource => &[
            ("id", Value::Null),
            ("is_primary", json!(false)),
            ("source_type", json!("user")),
            ("user_confirmed", json!(false)),
            ("expected_profile_version", Value::Null),
        ],
        Operation::Evidence => &[
            ("source_url", Value::Null),
            ("source_description", Value::Null),
            ("user_confirmed", json!(false)),
            ("project", Value::Null),
        ],
        Operation::Patch => &[],
    };
    for (key, value) in defaults {
        out.entry((*key).to_owned())
            .or_insert_with(|| value.clone());
    }
    if matches!(operation, Operation::Evidence) && out.get("project").is_some_and(|p| !p.is_null())
    {
        if out.get("evidence_type") != Some(&json!("project")) {
            return Err(invalid());
        }
        if out["project"]["url"]
            .as_str()
            .is_some_and(|url| public_https(url).is_none())
        {
            return Err(invalid());
        }
    }
    Ok(Value::Object(out))
}
/// Corrections invalidate old confirmation unless an explicit new decision accompanies them.
pub fn merge_evidence(current: Value, patch: Value) -> Result<Value> {
    let mut base = current.as_object().ok_or_else(invalid)?.clone();
    base.retain(|key, _| {
        [
            "evidence_type",
            "title",
            "content",
            "source_url",
            "source_description",
            "user_confirmed",
            "project",
        ]
        .contains(&key.as_str())
    });
    let patch = normalize(Operation::Patch, patch)?;
    let changes = patch.as_object().unwrap();
    if !changes.contains_key("user_confirmed") && changes.keys().any(|key| key != "user_confirmed")
    {
        base.insert("user_confirmed".into(), json!(false));
    }
    base.extend(changes.clone());
    normalize(Operation::Evidence, Value::Object(base))
}
