//! Local, frozen approved-project DTOs. Never fetch URLs or resolve external schemas.
use crate::{
    Failure, Result, profile_contract::legacy_word, resource_contract::boolean,
    resources::public_https,
};
use automated_apply_domain::text::folded;
use serde_json::{Value, json};
use std::{collections::HashSet, sync::LazyLock};

#[derive(Clone, Copy)]
pub enum Kind {
    Configuration,
    Knowledge,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(source: &str) -> Contract {
    let schema: Value = serde_json::from_str(source).expect("frozen local context schema");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(false)
        .build(&schema)
        .expect("frozen context validator");
    Contract { schema, validator }
}
fn contract(kind: Kind) -> &'static Contract {
    static CONFIGURATION: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../schemas/context-configuration.json")));
    static KNOWLEDGE: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../schemas/context-knowledge.json")));
    match kind {
        Kind::Configuration => &CONFIGURATION,
        Kind::Knowledge => &KNOWLEDGE,
    }
}
fn invalid() -> Failure {
    Failure("invalid_project_context_record")
}
pub(crate) fn python_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}
/// Exact bounded integer conversion; version counters must never round through f64.
pub(crate) fn integer(value: Value) -> Result<Value> {
    if let Some(n) = value.as_i64() {
        return Ok(json!(n));
    }
    if let Some(n) = value.as_u64() {
        return Ok(json!(n));
    }
    match value {
        Value::Bool(v) => Ok(json!(if v { 1 } else { 0 })),
        Value::Number(n) => {
            let v = n.as_f64().ok_or_else(invalid)?;
            if v.is_finite()
                && v.fract() == 0.0
                && v >= i64::MIN as f64
                && v < 9223372036854775808.0
            {
                Ok(json!(v as i64))
            } else {
                Err(invalid())
            }
        }
        Value::String(v) => {
            // Pydantic integers accept ASCII digits, optional sign/underscores and zero fractions.
            let v = v.trim();
            if v.starts_with("+-") {
                return Err(invalid());
            }
            let v = v.strip_prefix('+').unwrap_or(v);
            let (whole, fraction) = v.split_once('.').map_or((v, None), |(a, b)| (a, Some(b)));
            if fraction.is_some_and(|s| s.is_empty() || !s.chars().all(|c| c == '0')) {
                return Err(invalid());
            }
            let digits = whole.strip_prefix('-').unwrap_or(whole).as_bytes();
            if digits.is_empty()
                || digits.iter().enumerate().any(|(i, c)| {
                    !c.is_ascii_digit()
                        && (*c != b'_'
                            || i == 0
                            || i + 1 == digits.len()
                            || !digits[i - 1].is_ascii_digit()
                            || !digits[i + 1].is_ascii_digit())
                })
            {
                return Err(invalid());
            }
            let cleaned = whole.replace('_', "");
            if let Ok(n) = cleaned.parse::<i64>() {
                Ok(json!(n))
            } else {
                cleaned
                    .parse::<u64>()
                    .map(|n| json!(n))
                    .map_err(|_| invalid())
            }
        }
        _ => Err(invalid()),
    }
}
fn walk(root: &Value, schema: &Value, input: Value, depth: usize) -> Result<Value> {
    if depth > 24 {
        return Err(invalid());
    }
    if let Some(reference) = schema["$ref"].as_str() {
        return walk(
            root,
            root.pointer(reference.strip_prefix('#').ok_or_else(invalid)?)
                .ok_or_else(invalid)?,
            input,
            depth + 1,
        );
    }
    // Pydantic's integer Literal[1] canonicalizes numeric equality, including True.
    if schema.get("const") == Some(&json!(1)) && (input == true || input.as_f64() == Some(1.0)) {
        return Ok(json!(1));
    }
    // String literals/enums are validated before general string coercion.
    if schema.get("const").is_some() || schema.get("enum").is_some() {
        return Ok(input);
    }
    if let Some(choices) = schema["anyOf"].as_array() {
        if input.is_null() && choices.iter().any(|s| s["type"] == "null") {
            return Ok(Value::Null);
        }
        let choice = choices
            .iter()
            .find(|s| s["type"] != "null")
            .ok_or_else(invalid)?;
        return walk(root, choice, input, depth + 1);
    }
    match schema["type"].as_str() {
        Some("string") => {
            let value = input.as_str().ok_or_else(invalid)?;
            if schema["format"] == "uri" {
                return public_https(value).map(|s| json!(s)).ok_or_else(invalid);
            }
            Ok(json!(value.trim()))
        }
        Some("integer") => integer(input),
        Some("boolean") => boolean(&input).map_err(|_| invalid()),
        Some("array") => {
            let values = input.as_array().ok_or_else(invalid)?;
            if values.len() > 2000 {
                return Err(invalid());
            }
            values
                .iter()
                .map(|v| walk(root, &schema["items"], v.clone(), depth + 1))
                .collect::<Result<Vec<_>>>()
                .map(Value::Array)
        }
        Some("object") => {
            let mut values = input.as_object().ok_or_else(invalid)?.clone();
            let Some(properties) = schema["properties"].as_object() else {
                return Ok(Value::Object(values));
            };
            let title = schema["title"].as_str().unwrap_or("");
            for (key, property) in properties {
                let value = values
                    .remove(key)
                    .or_else(|| property.get("default").cloned())
                    .or_else(|| factory(title, key));
                if let Some(mut value) = value {
                    // Legacy prevalidators treat blank links as missing, using Python strip.
                    if (title == "ProfileLinks"
                        || title == "ProjectConfiguration"
                            && matches!(key.as_str(), "repository_url" | "live_url"))
                        && value
                            .as_str()
                            .is_some_and(|s| s.trim_matches(python_space).is_empty())
                    {
                        value = Value::Null;
                    }
                    values.insert(key.clone(), walk(root, property, value, depth + 1)?);
                }
            }
            let value = Value::Object(values);
            model(title, &value)?;
            Ok(value)
        }
        _ => Ok(input),
    }
}
fn factory(title: &str, key: &str) -> Option<Value> {
    match (title, key) {
        ("ConfigurationRecord", "configuration") | ("CandidateConfiguration", "links") => {
            Some(json!({}))
        }
        ("CandidateConfiguration", "projects") => Some(json!(
            (1..=3)
                .map(|i| json!({"id":format!("project-{i:02}"),"priority":i}))
                .collect::<Vec<_>>()
        )),
        _ => None,
    }
}
fn model(title: &str, value: &Value) -> Result<()> {
    match title {
        "CandidateConfiguration" => {
            let mut ids = HashSet::new();
            let mut priorities = HashSet::new();
            for project in value["projects"].as_array().ok_or_else(invalid)? {
                if !ids.insert(project["id"].clone())
                    || !priorities.insert(project["priority"].clone())
                {
                    return Err(invalid());
                }
            }
        }
        "ProjectConfiguration" => {
            if let Some(url) = value["repository_url"].as_str() {
                let url = reqwest::Url::parse(url).map_err(|_| invalid())?;
                let parts: Vec<_> = url.path().trim_end_matches('/').split('/').collect();
                if url.host_str() != Some("github.com")
                    || url.query().is_some_and(|s| !s.is_empty())
                    || url.fragment().is_some_and(|s| !s.is_empty())
                    || parts.len() != 3
                    || !parts[0].is_empty()
                    || parts[1..].iter().any(|s| {
                        s.is_empty()
                            || !s
                                .chars()
                                .all(|c| c.is_ascii_alphanumeric() || "_.-".contains(c))
                    })
                    || url.path().ends_with("//")
                {
                    return Err(invalid());
                }
            }
            let mut seen = HashSet::new();
            for stack in value["tech_stack"].as_array().ok_or_else(invalid)? {
                let s = stack.as_str().ok_or_else(invalid)?;
                if !(1..=60).contains(&s.chars().count())
                    || !s.chars().all(|c| legacy_word(c) || " .+#/-".contains(c))
                    || !seen.insert(folded(s))
                {
                    return Err(invalid());
                }
            }
            let path = value["context_file"].as_str().ok_or_else(invalid)?;
            let filename = path
                .split('/')
                .rfind(|s| !s.is_empty() && *s != ".")
                .unwrap_or("");
            if !path.is_empty()
                && (!path.starts_with("candidate_context/")
                    || path.contains('\\')
                    || path.split('/').any(|s| s == "..")
                    || !filename.ends_with(".md")
                    || filename == ".md")
            {
                return Err(invalid());
            }
        }
        "EvidenceReference" => {
            let path = value["file"].as_str().ok_or_else(invalid)?;
            if path.starts_with('/')
                || path.contains('\\')
                || path.split('/').any(|s| s == "..")
                || value["line_end"].as_i64().ok_or_else(invalid)?
                    < value["line_start"].as_i64().ok_or_else(invalid)?
            {
                return Err(invalid());
            }
        }
        _ => (),
    }
    Ok(())
}
fn drive(value: &mut Value) -> Result<()> {
    let input = value["canonical_url"].as_str().ok_or_else(invalid)?;
    let file = value["file_id"].as_str().ok_or_else(invalid)?;
    let canonical = format!("https://drive.google.com/file/d/{file}/view");
    let (without_fragment, fragment) = input.split_once('#').map_or((input, ""), |(a, b)| (a, b));
    if !input.is_ascii() || input.chars().any(|c| c <= ' ') || !fragment.is_empty() {
        return Err(invalid());
    }
    let (base, query) = without_fragment
        .split_once('?')
        .map_or((without_fragment, None), |(a, b)| (a, Some(b)));
    if base != canonical {
        return Err(invalid());
    }
    if let Some(query) = query.filter(|s| !s.is_empty()) {
        let fields: Vec<_> = query.split('&').collect();
        if fields.len() != 1 {
            return Err(invalid());
        }
        let (key, _) = fields[0].split_once('=').ok_or_else(invalid)?;
        if percent_encoding::percent_decode_str(key).decode_utf8_lossy() != "usp" {
            return Err(invalid());
        }
    }
    value["canonical_url"] = json!(canonical);
    Ok(())
}
/// Validates stored records without deriving any new approval or personal fact.
pub fn normalize(kind: Kind, input: Value) -> Result<Value> {
    // Local persisted data is still bounded before recursive processing.
    if crate::python_json::serialize(&input, true, false).len() > 8 * 1024 * 1024 {
        return Err(Failure("project_context_limit"));
    }
    let c = contract(kind);
    let mut value = walk(&c.schema, &c.schema, input, 0)?;
    if !c.validator.is_valid(&value) {
        return Err(invalid());
    }
    if matches!(kind, Kind::Configuration) && !value["configuration"]["resume"].is_null() {
        drive(&mut value["configuration"]["resume"])?;
    }
    Ok(value)
}
