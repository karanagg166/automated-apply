//! Actual three-role workspace DTOs and legacy Python content bindings.
use crate::{Failure, Result};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::sync::LazyLock;
#[derive(Clone, Copy)]
pub enum Kind {
    Consent,
    Draft,
    Approval,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(raw: &str) -> Contract {
    let schema: Value = serde_json::from_str(raw).expect("frozen Gmail workspace contract");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(true)
        .build(&schema)
        .expect("Gmail workspace schema");
    Contract { schema, validator }
}
fn contract(kind: Kind) -> &'static Contract {
    static CONSENT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-workspace-consent.json")));
    static DRAFT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-workspace-draft.json")));
    static APPROVAL: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-workspace-approval.json")));
    match kind {
        Kind::Consent => &CONSENT,
        Kind::Draft => &DRAFT,
        Kind::Approval => &APPROVAL,
    }
}
fn invalid() -> Failure {
    Failure("invalid_gmail_workspace_contract")
}
fn coerce(schema: &Value, value: &mut Value) -> Result<()> {
    if value.is_null() {
        return Ok(());
    }
    if let Some(children) = schema["anyOf"].as_array() {
        return coerce(
            children
                .iter()
                .find(|s| s["type"] != "null")
                .ok_or_else(invalid)?,
            value,
        );
    }
    match schema["type"].as_str() {
        Some("object") => {
            let body = value.as_object_mut().ok_or_else(invalid)?;
            for (key, child) in schema["properties"].as_object().ok_or_else(invalid)? {
                if !body.contains_key(key) {
                    if let Some(default) = child.get("default") {
                        body.insert(key.clone(), default.clone());
                    }
                }
                if let Some(value) = body.get_mut(key) {
                    coerce(child, value)?;
                }
            }
        }
        Some("integer") => {
            *value =
                crate::profile_contract::number(schema, value.clone()).map_err(|_| invalid())?
        }
        Some("boolean") => {
            if !value.is_boolean() {
                return Err(invalid());
            }
        }
        Some("string") => {
            let text = value
                .as_str()
                .ok_or_else(invalid)?
                .trim_matches(crate::context_contract::python_space);
            *value = if schema["format"] == "email" {
                json!(crate::profile_contract::email(text).map_err(|_| invalid())?)
            } else {
                json!(text)
            };
        }
        _ => {}
    }
    Ok(())
}
pub fn normalize(kind: Kind, mut value: Value) -> Result<Value> {
    let contract = contract(kind);
    coerce(&contract.schema, &mut value)?;
    if !contract.validator.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
pub fn digest(content: &Value) -> String {
    format!(
        "{:x}",
        Sha256::digest(crate::python_json::serialize(content, false, true).as_bytes())
    )
}
pub fn content(input: &Value, profile: &Value) -> Result<Value> {
    let name = profile["full_name"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or(Failure("current_approved_profile_required"))?;
    let company = input["company"].as_str().ok_or_else(invalid)?;
    let role = input["role"].as_str().ok_or_else(invalid)?;
    let context = input["context"].as_str().ok_or_else(invalid)?;
    let skills = profile["verified_skills"]
        .as_array()
        .ok_or(Failure("current_approved_profile_required"))?
        .iter()
        .take(4)
        .map(|s| {
            s.as_str()
                .ok_or(Failure("current_approved_profile_required"))
        })
        .collect::<Result<Vec<_>>>()?
        .join(", ");
    let subject = input["subject"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| format!("{role} opportunities at {company}"));
    let body=input["body"].as_str().map(str::to_owned).unwrap_or_else(||format!("Hello,\n\nI’m {name}. I’m interested in {role} opportunities at {company}. {context}\n\nMy verified skills include {skills}. I would welcome a conversation.\n\nThank you,\n{name}"));
    let recipient = input["recipient"].as_str().ok_or_else(invalid)?;
    if [recipient, subject.as_str()]
        .iter()
        .any(|s| s.chars().any(|c| matches!(c, '\r' | '\n' | '\0')))
    {
        return Err(Failure("gmail_draft_header_invalid"));
    }
    Ok(json!({"recipient":recipient,"subject":subject,"body":body}))
}
