//! Frozen selected-mailbox DTOs. Strict consent fields never accept coercion.
use super::*;
use std::sync::LazyLock;
#[derive(Clone, Copy)]
pub enum Kind {
    Connect,
    Policy,
    LeadImport,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(raw: &str) -> Contract {
    let schema: Value = serde_json::from_str(raw).expect("frozen Gmail read contract");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(true)
        .build(&schema)
        .expect("Gmail read schema");
    Contract { schema, validator }
}
fn contract(kind: Kind) -> &'static Contract {
    static CONNECT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-read-connect.json")));
    static POLICY: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-read-policy.json")));
    static LEAD: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-lead-import.json")));
    match kind {
        Kind::Connect => &CONNECT,
        Kind::Policy => &POLICY,
        Kind::LeadImport => &LEAD,
    }
}
fn invalid() -> Failure {
    Failure("invalid_gmail_read_contract")
}
fn normalize_value(schema: &Value, value: &mut Value) -> Result<()> {
    if value.is_null() {
        return Ok(());
    }
    if let Some(choices) = schema["anyOf"].as_array() {
        let child = choices
            .iter()
            .find(|v| v["type"] != "null")
            .ok_or_else(invalid)?;
        return normalize_value(child, value);
    }
    match schema["type"].as_str() {
        Some("object") => {
            let object = value.as_object_mut().ok_or_else(invalid)?;
            for (key, schema) in schema["properties"].as_object().ok_or_else(invalid)? {
                if !object.contains_key(key) {
                    if let Some(default) = schema.get("default") {
                        object.insert(key.clone(), default.clone());
                    } else if schema["type"] == "array" {
                        object.insert(key.clone(), json!([]));
                    }
                }
                if let Some(value) = object.get_mut(key) {
                    normalize_value(schema, value)?;
                }
            }
        }
        Some("array") => {
            for value in value.as_array_mut().ok_or_else(invalid)? {
                normalize_value(&schema["items"], value)?;
            }
        }
        Some("string") => {
            if schema.get("enum").is_some() || schema.get("const").is_some() {
                return Ok(());
            }
            let text = value
                .as_str()
                .ok_or_else(invalid)?
                .trim_matches(crate::context_contract::python_space);
            *value = match schema["format"].as_str() {
                Some("email") => {
                    json!(crate::profile_contract::email(text).map_err(|_| invalid())?)
                }
                Some("uri") => json!(crate::resources::public_https(text).ok_or_else(invalid)?),
                _ => json!(text),
            };
        }
        Some("integer") => {
            *value =
                crate::profile_contract::number(schema, value.clone()).map_err(|_| invalid())?;
        }
        Some("boolean") if !value.is_boolean() => {
            return Err(invalid());
        }
        _ => {}
    }
    Ok(())
}
pub fn normalize(kind: Kind, mut value: Value) -> Result<Value> {
    let contract = contract(kind);
    normalize_value(&contract.schema, &mut value)?;
    if !contract.validator.is_valid(&value) {
        return Err(invalid());
    }
    match kind {
        Kind::Connect if value["account_consent"] != true => return Err(invalid()),
        Kind::LeadImport if value["reviewed_job_evidence"] != true => return Err(invalid()),
        Kind::Policy => {
            if value["label_allowlist"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .any(|v| {
                    v.as_str()
                        .and_then(|s| s.strip_prefix("Label_"))
                        .is_none_or(|s| {
                            s.is_empty()
                                || s.len() > 100
                                || !s
                                    .bytes()
                                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
                        })
                })
            {
                return Err(invalid());
            }
            let folders = value["folders"].as_array().ok_or_else(invalid)?;
            let mut seen = std::collections::BTreeSet::new();
            if folders.iter().any(|v| !seen.insert(v.as_str().unwrap())) {
                return Err(invalid());
            }
            if (!value["history_months"].is_null() || !folders.is_empty())
                && value["max_pages"] != 1
                || !value["history_months"].is_null() && folders.is_empty()
            {
                return Err(invalid());
            }
            let labels = !value["label_allowlist"]
                .as_array()
                .ok_or_else(invalid)?
                .is_empty();
            let senders = !value["sender_allowlist"]
                .as_array()
                .ok_or_else(invalid)?
                .is_empty();
            if value["enabled"] == true
                && (!senders && !labels && folders.is_empty()
                    || value["read_body"] != true && !labels && folders.is_empty())
                || value["read_body"] == true && value["body_purpose"].is_null()
                || !value["query_allowlist"].is_null() && value["read_body"] != true
            {
                return Err(invalid());
            }
        }
        _ => {}
    }
    Ok(value)
}
