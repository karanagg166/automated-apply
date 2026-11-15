//! Faithful saved DTO projection. Read normalization cannot grant approval or alter stored history.
use crate::{Failure, Result, profile_contract, resource_contract};
use serde_json::{Map, Value, json};
use speedate::{
    DateTime, DateTimeConfig, MicrosecondsPrecisionOverflowBehavior, Time, TimeConfig,
    TimestampUnit,
};
use std::sync::LazyLock;
use uuid::Uuid;

#[derive(Clone, Copy)]
pub enum Kind {
    Snapshot,
    Field,
    Event,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(source: &str) -> Contract {
    let schema: Value = serde_json::from_str(source).expect("frozen packet DTO schema");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(false)
        .build(&schema)
        .expect("local packet DTO validator");
    Contract { schema, validator }
}
fn contract(kind: Kind) -> &'static Contract {
    static SNAPSHOT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../schemas/packet-snapshot.json")));
    static FIELD: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../schemas/packet-field.json")));
    static EVENT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../schemas/packet-event.json")));
    match kind {
        Kind::Snapshot => &SNAPSHOT,
        Kind::Field => &FIELD,
        Kind::Event => &EVENT,
    }
}
fn invalid() -> Failure {
    Failure("invalid_packet_saved_record")
}
fn datetime(value: &Value, attach_utc: bool) -> Result<DateTime> {
    let config = DateTimeConfig {
        timestamp_unit: TimestampUnit::Infer,
        time_config: TimeConfig {
            microseconds_precision_overflow_behavior:
                MicrosecondsPrecisionOverflowBehavior::Truncate,
            unix_timestamp_offset: Some(0),
        },
    };
    let result = match value {
        Value::String(s) => DateTime::parse_str_with_config(s, &config).or_else(|_| {
            speedate::Date::parse_str(s).map(|date| DateTime {
                date,
                time: Time {
                    hour: 0,
                    minute: 0,
                    second: 0,
                    microsecond: 0,
                    tz_offset: None,
                },
            })
        }),
        Value::Number(n) => {
            if let Some(n) = n.as_i64() {
                DateTime::from_timestamp_with_config(n, 0, &config)
            } else {
                DateTime::from_float_with_config(n.as_f64().ok_or_else(invalid)?, &config)
            }
        }
        _ => return Err(invalid()),
    };
    let mut date = result.map_err(|_| invalid())?;
    if date.date.year == 0 {
        return Err(invalid());
    }
    if attach_utc && date.time.tz_offset.is_none() {
        date.time.tz_offset = Some(0);
    }
    Ok(date)
}
pub(crate) fn timestamp(value: &Value, attach_utc: bool) -> Result<Value> {
    Ok(json!(datetime(value, attach_utc)?.to_string()))
}
/// Expiry needs an explicit timezone. The legacy comparison cannot safely interpret a naive value.
pub fn expiry(value: &Value) -> Result<Option<chrono::DateTime<chrono::Utc>>> {
    if value.is_null() {
        return Ok(None);
    }
    let date = datetime(value, false)?;
    if date.time.tz_offset.is_none() {
        return Err(invalid());
    }
    chrono::DateTime::from_timestamp(date.timestamp_tz(), date.time.microsecond * 1000)
        .map(Some)
        .ok_or_else(invalid)
}
fn float(value: Value) -> Result<Value> {
    let n = match value {
        Value::Number(n) => n.as_f64().ok_or_else(invalid)?,
        Value::Bool(v) => {
            if v {
                1.0
            } else {
                0.0
            }
        }
        Value::String(s) => {
            let s = s.trim();
            let bytes = s.as_bytes();
            if bytes.iter().enumerate().any(|(i, b)| {
                *b == b'_'
                    && (i == 0
                        || i + 1 == bytes.len()
                        || !bytes[i - 1].is_ascii_digit()
                        || !bytes[i + 1].is_ascii_digit())
            }) {
                return Err(invalid());
            }
            s.replace('_', "").parse::<f64>().map_err(|_| invalid())?
        }
        _ => return Err(invalid()),
    };
    if n.is_finite() {
        Ok(json!(n))
    } else {
        Err(invalid())
    }
}
fn factory(schema: &Value, key: &str, required: bool) -> Option<Value> {
    if required {
        return None;
    }
    match schema["type"].as_str() {
        Some("array") => Some(json!([])),
        Some("object") => Some(json!({})),
        _ if key == "provenance" => Some(json!({})),
        _ => None,
    }
}
fn walk(
    root: &Value,
    schema: &Value,
    input: Value,
    depth: usize,
    strip: bool,
    ignore_extra: bool,
    name: &str,
) -> Result<Value> {
    if depth > 32 {
        return Err(invalid());
    }
    if let Some(reference) = schema["$ref"].as_str() {
        let schema = root
            .pointer(reference.strip_prefix('#').ok_or_else(invalid)?)
            .ok_or_else(invalid)?;
        if schema["title"] == "CandidateProfileCreate" {
            return profile_contract::normalize(profile_contract::Operation::Create, input)
                .map_err(|_| invalid());
        }
        let plain = schema["title"] == "DiscoveryMatch";
        return walk(
            root,
            schema,
            input,
            depth + 1,
            if plain { false } else { strip },
            plain,
            name,
        );
    }
    if schema.get("enum").is_some() || schema.get("const").is_some() {
        return Ok(input);
    }
    if let Some(choices) = schema["anyOf"].as_array() {
        if input.is_null() && choices.iter().any(|c| c["type"] == "null") {
            return Ok(Value::Null);
        }
        return walk(
            root,
            choices
                .iter()
                .find(|c| c["type"] != "null")
                .ok_or_else(invalid)?,
            input,
            depth + 1,
            strip,
            ignore_extra,
            name,
        );
    }
    match schema["type"].as_str() {
        Some("string") => {
            match schema["format"].as_str() {
                Some("uuid") => {
                    return input
                        .as_str()
                        .and_then(|s| s.parse::<Uuid>().ok())
                        .map(|id| json!(id))
                        .ok_or_else(invalid);
                }
                Some("date-time") => {
                    return Ok(json!(
                        datetime(&input, matches!(name, "created_at" | "updated_at"))?.to_string()
                    ));
                }
                _ => (),
            }
            let s = input.as_str().ok_or_else(invalid)?;
            Ok(json!(if strip { s.trim() } else { s }))
        }
        Some("integer") => crate::context_contract::integer(input).map_err(|_| invalid()),
        Some("number") => float(input),
        Some("boolean") => resource_contract::boolean(&input).map_err(|_| invalid()),
        Some("array") => input
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .map(|v| {
                walk(
                    root,
                    &schema["items"],
                    v.clone(),
                    depth + 1,
                    strip,
                    false,
                    name,
                )
            })
            .collect::<Result<Vec<_>>>()
            .map(Value::Array),
        Some("object") => {
            let source = input.as_object().ok_or_else(invalid)?;
            let Some(properties) = schema["properties"].as_object() else {
                if let Some(item) = schema.get("additionalProperties").filter(|s| s.is_object()) {
                    return source
                        .iter()
                        .map(|(k, v)| {
                            walk(root, item, v.clone(), depth + 1, strip, false, k)
                                .map(|v| (k.clone(), v))
                        })
                        .collect::<Result<Map<_, _>>>()
                        .map(Value::Object);
                }
                return Ok(input);
            };
            if !ignore_extra
                && schema["additionalProperties"] == false
                && source.keys().any(|k| !properties.contains_key(k))
            {
                return Err(invalid());
            }
            let required = schema["required"].as_array();
            let mut result = Map::new();
            for (key, property) in properties {
                let required = required.is_some_and(|r| r.iter().any(|k| k == key));
                let value = source
                    .get(key)
                    .cloned()
                    .or_else(|| property.get("default").cloned())
                    .or_else(|| factory(property, key, required));
                if let Some(value) = value {
                    result.insert(
                        key.clone(),
                        walk(root, property, value, depth + 1, strip, false, key)?,
                    );
                }
            }
            Ok(Value::Object(result))
        }
        _ => Ok(input),
    }
}
/// Fields/events come from ORM rows (extra columns ignored); snapshots come from closed JSON contracts.
pub fn normalize(kind: Kind, mut raw: Value) -> Result<Value> {
    let effective = if matches!(kind, Kind::Field) {
        let mut question = raw.as_object().ok_or_else(invalid)?.clone();
        question.retain(|k, _| {
            [
                "question",
                "category",
                "field_type",
                "required",
                "max_characters",
                "max_words",
                "constraints",
                "options",
                "writing_style",
            ]
            .contains(&k.as_str())
        });
        let normalized =
            crate::packet_contract::question(Value::Object(question)).map_err(|_| invalid())?;
        raw.as_object_mut().unwrap().extend(
            serde_json::to_value(normalized)
                .unwrap()
                .as_object()
                .unwrap()
                .clone(),
        );
        Some(if raw["human_answer"].is_null() {
            raw["proposed_answer"].clone()
        } else {
            raw["human_answer"].clone()
        })
    } else {
        None
    };
    let contract = contract(kind);
    let mut value = walk(
        &contract.schema,
        &contract.schema,
        raw,
        0,
        true,
        !matches!(kind, Kind::Snapshot),
        "",
    )?;
    if !contract.validator.is_valid(&value) {
        return Err(invalid());
    }
    if let Some(effective) = effective {
        value["effective_answer"] = effective;
    }
    Ok(value)
}
