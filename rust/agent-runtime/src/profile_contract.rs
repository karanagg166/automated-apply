//! Pure compatibility normalization. No profile/database/provider access.
use crate::{Failure, Result};
use automated_apply_domain::text::folded;
use chrono::{DateTime, NaiveDate};
use regex::Regex;
use serde::Deserialize;
use serde_json::{Map, Value, json};
use std::{
    collections::{HashMap, HashSet},
    sync::LazyLock,
};
use unicode_normalization::UnicodeNormalization;

#[derive(Clone, Copy)]
pub enum Operation {
    Create,
    Update,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn contract(operation: Operation) -> &'static Contract {
    static CREATE: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../schemas/profile-create.json")));
    static UPDATE: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../schemas/profile-update.json")));
    match operation {
        Operation::Create => &CREATE,
        Operation::Update => &UPDATE,
    }
}
fn compile(source: &str) -> Contract {
    let schema: Value = serde_json::from_str(source).expect("public profile schema");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(false)
        .build(&schema)
        .expect("local public profile schema");
    Contract { schema, validator }
}
fn invalid() -> Failure {
    Failure("invalid_profile_input")
}
fn whitespace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}
fn collapse(value: &str) -> String {
    value
        .split(whitespace)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
/// Returns only validated canonical JSON. Updates preserve omission separately from null.
/// This module is not installed as an owner API until differential acceptance is complete.
pub fn normalize(operation: Operation, input: Value) -> Result<Value> {
    if !input.is_object()
        || matches!(operation, Operation::Update) && input.as_object().is_some_and(Map::is_empty)
    {
        return Err(invalid());
    }
    let c = contract(operation);
    let original = matches!(operation, Operation::Update).then(|| input.clone());
    let mut value = walk(&c.schema, &c.schema, input, "", false)?;
    if !c.validator.is_valid(&value) {
        return Err(invalid());
    }
    if let Some(original) = original {
        prune_unset(&mut value, &original);
    }
    Ok(value)
}
/// ORM root scalars only strip whitespace; nested JSON objects retain dict normalization.
/// This distinction preserves the legacy read contract without rewriting stored facts.
pub fn normalize_record(input: Value) -> Result<Value> {
    let c = contract(Operation::Create);
    let value = object(&c.schema, &c.schema, input, true)?;
    if !c.validator.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
fn prune_unset(value: &mut Value, input: &Value) {
    match (value, input) {
        (Value::Object(value), Value::Object(input)) => {
            value.retain(|key, _| input.contains_key(key));
            for (key, child) in value {
                prune_unset(child, &input[key]);
            }
        }
        (Value::Array(value), Value::Array(input)) => {
            for (child, source) in value.iter_mut().zip(input) {
                if child.is_object() {
                    prune_unset(child, source);
                }
            }
        }
        _ => {}
    }
}
fn walk(root: &Value, schema: &Value, input: Value, key: &str, in_list: bool) -> Result<Value> {
    if let Some(reference) = schema.get("$ref").and_then(Value::as_str) {
        let definition = root
            .pointer(reference.strip_prefix('#').ok_or_else(invalid)?)
            .ok_or_else(invalid)?;
        return walk(root, definition, input, key, in_list);
    }
    if let Some(options) = schema.get("anyOf").and_then(Value::as_array) {
        for option in options {
            if let Ok(value) = walk(root, option, input.clone(), key, in_list) {
                return Ok(value);
            }
        }
        return Err(invalid());
    }
    if key == "amount" {
        return decimal(input).map(Value::String);
    }
    match schema.get("type").and_then(Value::as_str) {
        Some("object") => object(root, schema, input, false),
        Some("array") => {
            let list = input.as_array().ok_or_else(invalid)?;
            if schema
                .get("maxItems")
                .and_then(Value::as_u64)
                .is_some_and(|max| list.len() > max as usize)
            {
                return Err(invalid());
            }
            let item = schema.get("items").ok_or_else(invalid)?;
            let mut result = list
                .iter()
                .map(|value| walk(root, item, value.clone(), key, true))
                .collect::<Result<Vec<_>>>()?;
            if result.iter().all(Value::is_string) {
                let mut seen = HashSet::new();
                let mut cleaned = Vec::new();
                for value in result {
                    let text = collapse(value.as_str().unwrap());
                    if text.is_empty() {
                        return Err(invalid());
                    }
                    if seen.insert(folded(&text)) {
                        cleaned.push(Value::String(text));
                    }
                }
                result = cleaned;
            }
            Ok(Value::Array(result))
        }
        Some("null") if input.is_null() => Ok(input),
        Some("boolean") => {
            if input.is_boolean() {
                return Ok(input);
            }
            if key != "prioritize_startups" {
                return Err(invalid());
            }
            if let Some(number) = input.as_f64() {
                return match number {
                    0.0 => Ok(json!(false)),
                    1.0 => Ok(json!(true)),
                    _ => Err(invalid()),
                };
            }
            let text = match input {
                Value::Number(n) => n.to_string(),
                Value::String(s) => collapse(&s).to_ascii_lowercase(),
                _ => return Err(invalid()),
            };
            match text.as_str() {
                "1" | "true" | "t" | "yes" | "y" | "on" => Ok(json!(true)),
                "0" | "false" | "f" | "no" | "n" | "off" => Ok(json!(false)),
                _ => Err(invalid()),
            }
        }
        Some("integer") | Some("number") => number(schema, input),
        Some("string") => {
            if schema.get("format").and_then(Value::as_str) == Some("date") {
                return date(input).map(Value::String);
            }
            let raw = input.as_str().ok_or_else(invalid)?;
            let mut text = if in_list {
                raw.trim().to_owned()
            } else {
                collapse(raw)
            };
            if schema.get("format").and_then(Value::as_str) == Some("uri") {
                if text.len() > 2048 {
                    return Err(invalid());
                }
                let url = reqwest::Url::parse(&text).map_err(|_| invalid())?;
                if !matches!(url.scheme(), "http" | "https")
                    || url.host_str().is_none()
                    || !url.username().is_empty()
                    || url.password().is_some()
                {
                    return Err(invalid());
                }
                text = url.into();
            } else if schema.get("format").and_then(Value::as_str) == Some("email") {
                text = email(&text)?;
            }
            let count = text.chars().count() as u64;
            if schema
                .get("minLength")
                .and_then(Value::as_u64)
                .is_some_and(|min| count < min)
                || schema
                    .get("maxLength")
                    .and_then(Value::as_u64)
                    .is_some_and(|max| count > max)
            {
                return Err(invalid());
            }
            Ok(Value::String(text))
        }
        _ => Err(invalid()),
    }
}
fn object(root: &Value, schema: &Value, input: Value, orm: bool) -> Result<Value> {
    let input = input.as_object().ok_or_else(invalid)?;
    let properties = schema
        .get("properties")
        .and_then(Value::as_object)
        .ok_or_else(invalid)?;
    if input.keys().any(|key| !properties.contains_key(key)) {
        return Err(invalid());
    }
    let partial = schema
        .get("title")
        .and_then(Value::as_str)
        .is_some_and(|title| title.ends_with("Update"));
    let required = schema.get("required").and_then(Value::as_array);
    let mut output = Map::new();
    let mut bound = Map::new();
    for (key, field) in properties {
        if let Some(raw) = input.get(key) {
            let value = walk(root, field, raw.clone(), key, orm)?;
            output.insert(key.clone(), value.clone());
            bound.insert(key.clone(), value);
        } else if partial {
            bound.insert(key.clone(), Value::Null);
        } else {
            if required.is_some_and(|list| list.contains(&json!(key))) {
                return Err(invalid());
            }
            let value = if let Some(default) = field.get("default") {
                default.clone()
            } else if field.get("type") == Some(&json!("array")) {
                json!([])
            } else if field.get("$ref").is_some() {
                walk(root, field, json!({}), key, false)?
            } else {
                return Err(invalid());
            };
            output.insert(key.clone(), value.clone());
            bound.insert(key.clone(), value);
        }
    }
    if let (Some(start), Some(end)) = (
        output.get("start_date").and_then(Value::as_str),
        output.get("end_date").and_then(Value::as_str),
    ) && end < start
    {
        return Err(invalid());
    }
    if !partial && let Some(rows) = output.get("work_authorizations").and_then(Value::as_array) {
        let mut countries = HashSet::new();
        for row in rows {
            if !countries.insert(
                row.get("country_code")
                    .cloned()
                    .ok_or_else(invalid)?
                    .to_string(),
            ) {
                return Err(invalid());
            }
        }
    }
    if serde_json::to_vec(&bound).map_err(|_| invalid())?.len() > 65536 {
        return Err(Failure("profile_payload_limit"));
    }
    Ok(Value::Object(output))
}
pub(crate) fn number(schema: &Value, input: Value) -> Result<Value> {
    let integer = schema.get("type") == Some(&json!("integer"));
    let original = match input {
        Value::Number(n) => n.to_string(),
        Value::Bool(v) => if v { "1" } else { "0" }.into(),
        Value::String(s) => collapse(&s),
        _ => return Err(invalid()),
    };
    if integer && (original.contains(['e', 'E']) || !original.is_ascii()) {
        return Err(invalid());
    }
    let bytes = original.as_bytes();
    if bytes.iter().enumerate().any(|(i, &c)| {
        c == b'_'
            && (i == 0
                || i + 1 == bytes.len()
                || if integer {
                    !bytes[i - 1].is_ascii_digit() || !bytes[i + 1].is_ascii_digit()
                } else {
                    bytes[i - 1] == b'_' || bytes[i + 1] == b'_'
                })
    }) {
        return Err(invalid());
    }
    if integer
        && original.contains('.')
        && original
            .split_once('.')
            .is_some_and(|(a, b)| a.trim_start_matches(['+', '-']).is_empty() || b.is_empty())
    {
        return Err(invalid());
    }
    if integer
        && original
            .split_once('.')
            .is_some_and(|(_, fraction)| fraction.chars().any(|c| c != '0'))
    {
        return Err(invalid());
    }
    let text = original.replace('_', "");
    let value: f64 = text.parse().map_err(|_| invalid())?;
    if !value.is_finite()
        || schema
            .get("minimum")
            .and_then(Value::as_f64)
            .is_some_and(|min| value < min)
        || schema
            .get("maximum")
            .and_then(Value::as_f64)
            .is_some_and(|max| value > max)
    {
        return Err(invalid());
    }
    if integer {
        if value.fract() != 0.0 || value.abs() > i64::MAX as f64 {
            return Err(invalid());
        }
        Ok(json!(value as i64))
    } else {
        Ok(json!(value))
    }
}
pub(crate) fn resource_version(input: Value) -> Result<Value> {
    number(&json!({"type":"integer","minimum":1}), input)
}
pub(crate) fn pagination_integer(input: Value, min: i64, max: i64) -> Result<i64> {
    number(
        &json!({"type":"integer","minimum":min,"maximum":max}),
        input,
    )?
    .as_i64()
    .ok_or_else(invalid)
}
pub(crate) fn project(input: Value) -> Result<Value> {
    let c = contract(Operation::Create);
    walk(
        &c.schema,
        &c.schema["$defs"]["VerifiedProject"],
        input,
        "project",
        false,
    )
}
pub(crate) fn legacy_word(c: char) -> bool {
    contains(&unicode().word_ranges, c)
}
pub(crate) fn legacy_decimal(c: char) -> bool {
    c.is_ascii_digit() || unicode().decimal_digits.contains_key(&c)
}
pub(crate) fn decimal_digit(c: char) -> Option<u32> {
    c.to_digit(10).or_else(|| {
        unicode()
            .decimal_digits
            .get(&c)
            .and_then(|c| c.to_digit(10))
    })
}
fn calendar(text: &str) -> Result<String> {
    if text.len() != 10
        || text.as_bytes()[4] != b'-'
        || text.as_bytes()[7] != b'-'
        || text.starts_with("0000")
        || text
            .bytes()
            .enumerate()
            .any(|(i, c)| i != 4 && i != 7 && !c.is_ascii_digit())
    {
        return Err(invalid());
    }
    NaiveDate::parse_from_str(text, "%Y-%m-%d").map_err(|_| invalid())?;
    Ok(text.to_owned())
}
fn date(input: Value) -> Result<String> {
    if let Some(value) = input.as_str() {
        let text = collapse(value);
        if let Ok(date) = calendar(&text) {
            return Ok(date);
        }
        static DATETIME: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})[Tt _]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:[.,]([0-9]+))?)?([Zz]|[+-][0-9]{2}:?[0-9]{2})?$").unwrap()
        });
        if let Some(fields) = DATETIME.captures(&text) {
            let day = calendar(&fields[1])?;
            if &fields[2] != "00"
                || &fields[3] != "00"
                || fields
                    .get(4)
                    .is_some_and(|seconds| seconds.as_str() != "00")
                || fields
                    .get(5)
                    .is_some_and(|fraction| fraction.as_str().chars().take(6).any(|c| c != '0'))
            {
                return Err(invalid());
            }
            if let Some(zone) = fields.get(6)
                && zone.as_str().len() > 1
            {
                let offset = zone.as_str()[1..].replace(':', "");
                if offset[..2].parse::<u8>().unwrap() > 23
                    || offset[2..].parse::<u8>().unwrap() > 59
                {
                    return Err(invalid());
                }
            }
            return Ok(day);
        }
        return text
            .parse::<f64>()
            .map_err(|_| invalid())
            .and_then(timestamp_date);
    }
    input.as_f64().ok_or_else(invalid).and_then(timestamp_date)
}
fn timestamp_date(mut number: f64) -> Result<String> {
    if number.abs() > 20000000000.0 {
        number /= 1000.0;
    }
    if !number.is_finite() || number.fract() != 0.0 || number % 86400.0 != 0.0 {
        return Err(invalid());
    }
    let parsed = DateTime::from_timestamp(number as i64, 0).ok_or_else(invalid)?;
    let date = parsed.date_naive().to_string();
    if date.len() != 10 || date.starts_with("0000") {
        return Err(invalid());
    }
    Ok(date)
}
#[derive(Deserialize)]
struct UnicodeData {
    unsafe_ranges: Vec<[u32; 2]>,
    word_ranges: Vec<[u32; 2]>,
    decimal_digits: HashMap<char, char>,
    idna_pvalid: Vec<[u32; 2]>,
}
fn unicode() -> &'static UnicodeData {
    static DATA: LazyLock<UnicodeData> = LazyLock::new(|| {
        serde_json::from_str(include_str!("../schemas/profile-unicode.json")).unwrap()
    });
    &DATA
}
fn contains(ranges: &[[u32; 2]], c: char) -> bool {
    let value = c as u32;
    let index = ranges.partition_point(|range| range[1] < value);
    ranges.get(index).is_some_and(|range| range[0] <= value)
}
fn safe_email(text: &str) -> bool {
    static MARK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\p{M}").unwrap());
    if MARK.is_match(text) {
        return false;
    }
    text.chars().all(|c| !contains(&unicode().unsafe_ranges, c))
}
pub(crate) fn email(text: &str) -> Result<String> {
    let mut address = text;
    if let Some((display, rest)) = text.rsplit_once('<') {
        if !rest.ends_with('>') || !safe_email(&display.replace(' ', "")) {
            return Err(invalid());
        }
        address = rest[..rest.len() - 1].trim();
    }
    if address.len() > 254 {
        return Err(invalid());
    }
    let (local, domain) = address.rsplit_once('@').ok_or_else(invalid)?;
    let local: String = local.nfc().collect();
    if local.is_empty()
        || local.starts_with('.')
        || local.ends_with('.')
        || local.contains("..")
        || !safe_email(&local)
    {
        return Err(invalid());
    }
    if local
        .chars()
        .any(|c| c.is_ascii() && !c.is_ascii_alphanumeric() && !"._!#$%&'*+-/=?^`{|}~".contains(c))
    {
        return Err(invalid());
    }
    if domain.is_empty()
        || !safe_email(domain)
        || domain
            .chars()
            .any(|c| c.is_ascii() && !c.is_ascii_alphanumeric() && !".-".contains(c))
    {
        return Err(invalid());
    }
    let ascii = idna::domain_to_ascii_strict(domain).map_err(|_| invalid())?;
    if !ascii.contains('.')
        || ascii.ends_with('.')
        || ascii.len() > 253
        || !ascii
            .chars()
            .last()
            .is_some_and(|c| c.is_ascii_alphabetic())
    {
        return Err(invalid());
    }
    for label in ascii.split('.') {
        if label.is_empty() || label.len() > 63 || label.starts_with('-') || label.ends_with('-') {
            return Err(invalid());
        }
    }
    for reserved in ["arpa", "invalid", "local", "localhost", "onion", "test"] {
        if ascii == reserved || ascii.ends_with(&format!(".{reserved}")) {
            return Err(invalid());
        }
    }
    let (domain, status) = idna::domain_to_unicode(&ascii);
    status.map_err(|_| invalid())?;
    for label in domain.split('.') {
        let chars = label.chars().collect::<Vec<_>>();
        for (index, &c) in chars.iter().enumerate() {
            if contains(&unicode().idna_pvalid, c) {
                continue;
            }
            let context = match c {
                '·' => {
                    index > 0
                        && index + 1 < chars.len()
                        && chars[index - 1] == 'l'
                        && chars[index + 1] == 'l'
                }
                '͵' => chars.get(index + 1).is_some_and(|c| script(*c, "Greek")),
                '׳' | '״' => index > 0 && script(chars[index - 1], "Hebrew"),
                '・' => chars.iter().any(|c| {
                    *c != '・'
                        && ["Hiragana", "Katakana", "Han"]
                            .iter()
                            .any(|name| script(*c, name))
                }),
                '٠'..='٩' => !chars.iter().any(|c| ('۰'..='۹').contains(c)),
                '۰'..='۹' => !chars.iter().any(|c| ('٠'..='٩').contains(c)),
                _ => false,
            };
            if !context {
                return Err(invalid());
            }
        }
    }
    let local = if [
        "info",
        "marketing",
        "sales",
        "support",
        "abuse",
        "noc",
        "security",
        "postmaster",
        "hostmaster",
        "usenet",
        "news",
        "webmaster",
        "www",
        "uucp",
        "ftp",
    ]
    .contains(&local.to_ascii_lowercase().as_str())
    {
        local.to_ascii_lowercase()
    } else {
        local
    };
    let result = format!("{local}@{domain}");
    if address.len() > 254 || result.len() > 254 || local.len() + 1 + ascii.len() > 254 {
        return Err(invalid());
    }
    Ok(result)
}
fn script(c: char, name: &str) -> bool {
    static TABLE: LazyLock<HashMap<&str, Regex>> = LazyLock::new(|| {
        ["Greek", "Hebrew", "Hiragana", "Katakana", "Han"]
            .into_iter()
            .map(|name| (name, Regex::new(&format!(r"^\p{{{name}}}$")).unwrap()))
            .collect()
    });
    TABLE[name].is_match(&c.to_string())
}
fn decimal(input: Value) -> Result<String> {
    let source = match input {
        Value::String(s) => collapse(&s),
        Value::Number(n) => n.to_string(),
        _ => return Err(invalid()),
    };
    let mut text = String::new();
    for c in source.chars() {
        if c == '_' {
            continue;
        }
        if c.is_ascii() {
            text.push(c);
        } else if let Some(digit) = unicode().decimal_digits.get(&c) {
            text.push(*digit);
        } else {
            return Err(invalid());
        }
    }
    let negative = text.starts_with('-');
    let raw = text.strip_prefix(['+', '-']).unwrap_or(&text);
    let mut parts = raw.split(['e', 'E']);
    let mantissa = parts.next().unwrap_or("");
    let power = match parts.next() {
        Some(s) => s.parse::<i64>().map_err(|_| invalid())?,
        None => 0,
    };
    if parts.next().is_some() {
        return Err(invalid());
    }
    let mut digits = String::new();
    let mut scale = 0i64;
    let mut dot = false;
    for c in mantissa.chars() {
        if c == '.' && !dot {
            dot = true;
            continue;
        }
        if !c.is_ascii_digit() {
            return Err(invalid());
        }
        digits.push(c);
        if dot {
            scale += 1;
        }
    }
    if digits.is_empty() {
        return Err(invalid());
    }
    let exponent = power.checked_sub(scale).ok_or_else(invalid)?;
    let coefficient = digits.trim_start_matches('0');
    let coefficient = if coefficient.is_empty() {
        "0"
    } else {
        coefficient
    };
    let adjusted = exponent
        .checked_add(coefficient.len() as i64 - 1)
        .ok_or_else(invalid)?;
    let mut result = if exponent > 0 || adjusted < -6 {
        let mut s = coefficient[..1].to_owned();
        if coefficient.len() > 1 {
            s.push('.');
            s.push_str(&coefficient[1..]);
        }
        s.push('E');
        if adjusted >= 0 {
            s.push('+');
        }
        s.push_str(&adjusted.to_string());
        s
    } else if exponent == 0 {
        coefficient.into()
    } else {
        let position = coefficient.len() as i64 + exponent;
        if position > 0 {
            format!(
                "{}.{}",
                &coefficient[..position as usize],
                &coefficient[position as usize..]
            )
        } else {
            if position < -65536 {
                return Err(invalid());
            }
            format!("0.{}{}", "0".repeat((-position) as usize), coefficient)
        }
    };
    if negative {
        result.insert(0, '-');
    }
    if !crate::questions::valid_compensation_amount(&json!(result)) {
        return Err(invalid());
    }
    Ok(result)
}

/// Strong quoted numeric ETag only; preserve the existing public precondition bound.
pub fn parse_version(value: Option<&str>, required: bool) -> Result<Option<i32>> {
    let Some(value) = value else {
        return if required {
            Err(Failure("profile_version_required"))
        } else {
            Ok(None)
        };
    };
    if !(3..=12).contains(&value.len()) || !value.starts_with('"') || !value.ends_with('"') {
        return Err(Failure("profile_version_syntax"));
    }
    let digits = &value[1..value.len() - 1];
    if !digits.bytes().all(|c| c.is_ascii_digit()) {
        return Err(Failure("profile_version_syntax"));
    }
    let version = digits
        .parse::<i32>()
        .map_err(|_| Failure("invalid_profile_version"))?;
    if !(1..=2147483646).contains(&version) {
        return Err(Failure("invalid_profile_version"));
    }
    Ok(Some(version))
}

/// Merge only the supplied preferences keys, then validate the complete resulting profile.
/// Omitted verified facts are preserved; explicit null follows the original field contract.
pub fn merge_update(current: Value, patch: Value) -> Result<Value> {
    let mut current = normalize(Operation::Create, current)?;
    let mut patch = normalize(Operation::Update, patch)?;
    if let Some(preferences) = patch.as_object_mut().unwrap().remove("preferences") {
        let target = current
            .get_mut("preferences")
            .and_then(Value::as_object_mut)
            .ok_or_else(invalid)?;
        target.extend(preferences.as_object().ok_or_else(invalid)?.clone());
    }
    current
        .as_object_mut()
        .unwrap()
        .extend(patch.as_object().unwrap().clone());
    normalize(Operation::Create, current)
}
/// Existing production/staging placeholder fence. Never infer or save replacement facts.
pub fn reject_placeholders(value: &Value) -> Result<()> {
    static PATTERN: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)fictional|placeholder|YOUR_|example\.(?:com|org|net)|Alex Example|test@|(?P<example>\.example)|(?P<todo>TODO)").unwrap()
    });
    // Python re.I also treats these two characters as ASCII I. Regex word
    // boundaries use the pinned Python Unicode 14 alphanumeric/underscore set.
    let encoded = serde_json::to_string(value)
        .map_err(|_| invalid())?
        .replace(['\u{130}', '\u{131}'], "i");
    for found in PATTERN.captures_iter(&encoded) {
        let matched = found.get(0).unwrap();
        let before = encoded[..matched.start()]
            .chars()
            .next_back()
            .is_some_and(|c| contains(&unicode().word_ranges, c));
        let after = encoded[matched.end()..]
            .chars()
            .next()
            .is_some_and(|c| contains(&unicode().word_ranges, c));
        if found.name("example").is_some() && after {
            continue;
        }
        if found.name("todo").is_some() && (before || after) {
            continue;
        }
        return Err(Failure("fictional_or_placeholder_profile_rejected"));
    }
    Ok(())
}
