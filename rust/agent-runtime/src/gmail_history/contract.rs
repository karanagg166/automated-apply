//! Actual owner review DTOs. Selected mailbox evidence remains separate from confirmed history.
use super::*;
use chrono::{FixedOffset, SecondsFormat};
use std::sync::LazyLock;
#[derive(Clone, Copy)]
pub enum Kind {
    Review,
    Version,
    Retention,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(raw: &str) -> Contract {
    let schema: Value = serde_json::from_str(raw).expect("frozen Gmail contract");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(true)
        .build(&schema)
        .expect("Gmail schema");
    Contract { schema, validator }
}
fn schema(kind: Kind) -> &'static Contract {
    static REVIEW: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-history-review.json")));
    static VERSION: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-history-version.json")));
    static RETENTION: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/gmail-history-retention.json")));
    match kind {
        Kind::Review => &REVIEW,
        Kind::Version => &VERSION,
        Kind::Retention => &RETENTION,
    }
}
pub fn timestamp(value: &Value) -> Option<DateTime<FixedOffset>> {
    if let Some(raw) = value.as_str() {
        if let Ok(at) = DateTime::parse_from_rfc3339(raw) {
            return Some(at);
        }
        let mut raw = raw.to_owned();
        if raw.len() > 10 && matches!(raw.as_bytes()[10], b' ' | b't' | b'_') {
            raw.replace_range(10..11, "T");
        }
        if raw.ends_with('z') {
            raw.pop();
            raw.push('Z');
        }
        if let Ok(at) = DateTime::parse_from_rfc3339(&raw) {
            return Some(at);
        }
    }
    let mut number = match value {
        Value::Number(n) => n.as_f64()?,
        Value::String(s) => s.parse::<f64>().ok()?,
        _ => return None,
    };
    if !number.is_finite() {
        return None;
    }
    if number.abs() > 20_000_000_000.0 {
        number /= 1000.0;
    }
    if !(-62_135_596_800.0..=253_402_300_799.999_999).contains(&number) {
        return None;
    }
    DateTime::from_timestamp_micros((number * 1_000_000.0).round() as i64)
        .map(|at| at.fixed_offset())
}
pub fn normalize(kind: Kind, mut input: Value, now: DateTime<Utc>) -> Result<Value> {
    let invalid = || Failure("invalid_gmail_history_contract");
    let contract = schema(kind);
    let object = input.as_object_mut().ok_or_else(invalid)?;
    for key in ["expected_version", "retention_days"] {
        if let Some(value) = object.get_mut(key) {
            *value =
                crate::profile_contract::number(&contract.schema["properties"][key], value.clone())
                    .map_err(|_| invalid())?;
        }
    }
    if matches!(kind, Kind::Review) {
        if !object
            .get("confirmed_application")
            .is_some_and(Value::is_boolean)
            || object.get("owner_reviewed") != Some(&json!(true))
        {
            return Err(invalid());
        }
        for key in ["company", "role", "status"] {
            let text = object
                .get(key)
                .and_then(Value::as_str)
                .ok_or_else(invalid)?
                .trim_matches(crate::context_contract::python_space)
                .to_owned();
            object.insert(key.into(), json!(text));
        }
        let applied = timestamp(object.get("applied_at").ok_or_else(invalid)?)
            .filter(|at| *at <= now)
            .ok_or_else(invalid)?;
        object.insert(
            "applied_at".into(),
            json!(applied.to_rfc3339_opts(
                if applied.timestamp_subsec_micros() == 0 {
                    SecondsFormat::Secs
                } else {
                    SecondsFormat::Micros
                },
                true
            )),
        );
        let url = match object.get("job_url").unwrap_or(&Value::Null) {
            Value::Null => Value::Null,
            Value::String(s) => json!(crate::resources::public_https(s).ok_or_else(invalid)?),
            _ => return Err(invalid()),
        };
        object.insert("job_url".into(), url);
        let evidence = object
            .get("evidence")
            .and_then(Value::as_object)
            .filter(|e| !e.is_empty() && e.len() <= 2)
            .ok_or_else(invalid)?;
        let mut out = serde_json::Map::new();
        for (account, ids) in evidence {
            let account = account
                .parse::<uuid::Uuid>()
                .map_err(|_| invalid())?
                .to_string();
            let ids = ids
                .as_array()
                .filter(|ids| !ids.is_empty() && ids.len() <= 25)
                .ok_or_else(invalid)?;
            let ids = ids
                .iter()
                .map(|v| {
                    let id = v
                        .as_str()
                        .ok_or_else(invalid)?
                        .trim_matches(crate::context_contract::python_space);
                    if !identity(id) {
                        return Err(invalid());
                    }
                    Ok(json!(id))
                })
                .collect::<Result<Vec<_>>>()?;
            if out.insert(account, json!(ids)).is_some() {
                return Err(invalid());
            }
        }
        object.insert("evidence".into(), Value::Object(out));
    }
    if !contract.validator.is_valid(&input) {
        return Err(invalid());
    }
    Ok(input)
}
pub fn identity(raw: &str) -> bool {
    raw.len() == 32
        && raw
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub fn canonical(raw: Option<&str>) -> Option<String> {
    raw.and_then(|s| {
        crate::job_urls::ats(Some(s))
            .ok()
            .flatten()
            .or_else(|| crate::job_urls::canonical(s).ok())
    })
}
pub fn folded(raw: &str) -> String {
    automated_apply_domain::text::folded(raw.trim_matches(crate::context_contract::python_space))
}
pub fn opportunity(company: &str, role: &str, url: Option<&str>) -> String {
    canonical(url).unwrap_or_else(|| format!("{}\n{}", folded(company), folded(role)))
}
