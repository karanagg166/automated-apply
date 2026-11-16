//! Legacy Pydantic declaration-order hashes, including masked SecretStr and raw dict order.
//! The global serde_json map representation and unrelated fingerprint recipes stay unchanged.
use super::*;
use serde::Deserialize;
use serde::de::{self, MapAccess, SeqAccess, Visitor};

pub(super) static SCHEMA: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("../../../native-host/schemas/command.json"))
        .expect("frozen native schema")
});
static VALIDATOR: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
    jsonschema::draft202012::options()
        .should_validate_formats(true)
        .build(&SCHEMA)
        .expect("native schema")
});
static ORDER: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!(
        "../../schemas/native-command-field-order.json"
    ))
    .expect("frozen native field order")
});

#[derive(Default)]
enum InputOrder {
    Object(Vec<(String, Self)>),
    Array(Vec<Self>),
    #[default]
    Scalar,
}
static EMPTY_ORDER: InputOrder = InputOrder::Scalar;
impl InputOrder {
    fn field(&self, key: &str) -> &Self {
        match self {
            Self::Object(fields) => fields
                .iter()
                .find(|(k, _)| k == key)
                .map(|(_, v)| v)
                .unwrap_or(&EMPTY_ORDER),
            _ => &EMPTY_ORDER,
        }
    }
    fn item(&self, index: usize) -> &Self {
        match self {
            Self::Array(values) => values.get(index).unwrap_or(&EMPTY_ORDER),
            _ => &EMPTY_ORDER,
        }
    }
}
impl<'de> Deserialize<'de> for InputOrder {
    fn deserialize<D: de::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        struct Shape;
        impl<'de> Visitor<'de> for Shape {
            type Value = InputOrder;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("bounded JSON command")
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Self::Value, M::Error> {
                let mut fields = Vec::new();
                while let Some(field) = map.next_entry()? {
                    fields.push(field);
                }
                Ok(InputOrder::Object(fields))
            }
            fn visit_seq<S: SeqAccess<'de>>(
                self,
                mut sequence: S,
            ) -> std::result::Result<Self::Value, S::Error> {
                let mut values = Vec::new();
                while let Some(v) = sequence.next_element()? {
                    values.push(v);
                }
                Ok(InputOrder::Array(values))
            }
            fn visit_unit<E: de::Error>(self) -> std::result::Result<Self::Value, E> {
                Ok(InputOrder::Scalar)
            }
            fn visit_bool<E: de::Error>(self, _: bool) -> std::result::Result<Self::Value, E> {
                Ok(InputOrder::Scalar)
            }
            fn visit_i64<E: de::Error>(self, _: i64) -> std::result::Result<Self::Value, E> {
                Ok(InputOrder::Scalar)
            }
            fn visit_u64<E: de::Error>(self, _: u64) -> std::result::Result<Self::Value, E> {
                Ok(InputOrder::Scalar)
            }
            fn visit_f64<E: de::Error>(self, _: f64) -> std::result::Result<Self::Value, E> {
                Ok(InputOrder::Scalar)
            }
            fn visit_str<E: de::Error>(self, _: &str) -> std::result::Result<Self::Value, E> {
                Ok(InputOrder::Scalar)
            }
        }
        deserializer.deserialize_any(Shape)
    }
}
fn shape<'a>(schema: &'a Value, value: &Value) -> (&'a Value, Option<&'a str>) {
    if let Some(reference) = schema["$ref"].as_str()
        && let Some(path) = reference.strip_prefix('#')
        && let Some(schema) = SCHEMA.pointer(path)
    {
        return (schema, reference.rsplit('/').next());
    }
    if let Some(variants) = schema["anyOf"].as_array() {
        if value.is_null() {
            return (schema, None);
        }
        if let Some(selected) = variants.iter().find(|s| {
            s["type"] != "null"
                && (s.get("$ref").is_some()
                    || match s["type"].as_str() {
                        Some("object") => value.is_object(),
                        Some("array") => value.is_array(),
                        Some("string") => value.is_string(),
                        Some("integer" | "number") => value.is_number(),
                        Some("boolean") => value.is_boolean(),
                        _ => false,
                    })
        }) {
            return shape(selected, value);
        }
    }
    (schema, None)
}
fn normalize(schema: &Value, value: &mut Value) -> Result<()> {
    let (schema, model) = shape(schema, value);
    if let (Some(properties), Some(object)) =
        (schema["properties"].as_object(), value.as_object_mut())
    {
        for (key, schema) in properties {
            if !object.contains_key(key) {
                if let Some(default) = schema.get("default") {
                    object.insert(key.clone(), default.clone());
                }
            }
        }
    }
    // Container factories have no literal JSON-schema default.
    if let (Some(properties), Some(object)) =
        (schema["properties"].as_object(), value.as_object_mut())
    {
        for (key, child) in properties {
            if !object.contains_key(key)
                && !schema["required"]
                    .as_array()
                    .is_some_and(|r| r.iter().any(|v| v == key))
            {
                if child["type"] == "array" {
                    object.insert(key.clone(), json!([]));
                }
                if child["type"] == "object" {
                    object.insert(key.clone(), json!({}));
                }
            }
            if let Some(value) = object.get_mut(key) {
                normalize(child, value)?;
            }
        }
    }
    if let Some(array) = value.as_array_mut() {
        for value in array {
            normalize(&schema["items"], value)?;
        }
    }
    if schema["type"] == "number"
        && let Some(number) = value.as_f64()
    {
        *value = json!(number);
    }
    if let Some(text) = value.as_str() {
        if schema["format"] == "uuid" {
            *value = json!(text.parse::<Uuid>().map_err(|_| request_error())?);
        } else if schema["format"] == "uri" {
            *value = json!(crate::resources::public_https(text).ok_or_else(request_error)?);
        } else if schema["format"] == "date-time" {
            let date = DateTime::parse_from_rfc3339(text).map_err(|_| request_error())?;
            let fraction = date.timestamp_subsec_micros();
            let suffix = if date.offset().local_minus_utc() == 0 {
                "Z".into()
            } else {
                date.format("%:z").to_string()
            };
            *value = json!(format!(
                "{}{}{suffix}",
                date.format("%Y-%m-%dT%H:%M:%S"),
                if fraction == 0 {
                    String::new()
                } else {
                    format!(".{fraction:06}")
                }
            ));
        }
    }
    validate_model(model, value)
}
fn validate_model(model: Option<&str>, value: &mut Value) -> Result<()> {
    let stripped = |s: &str| {
        s.trim_matches(crate::context_contract::python_space)
            .to_owned()
    };
    match model {
        Some("ObservedNaukriJob") => {
            for key in ["title", "company", "location", "description"] {
                let text = stripped(value[key].as_str().ok_or_else(request_error)?);
                if text.is_empty() {
                    return Err(request_error());
                }
                value[key] = json!(text);
            }
            let mut seen = std::collections::HashSet::new();
            let mut skills = Vec::new();
            for raw in value["skills"].as_array().ok_or_else(request_error)? {
                let raw = raw.as_str().ok_or_else(request_error)?;
                let text = stripped(raw);
                if text.is_empty() || raw.chars().count() > 200 {
                    return Err(request_error());
                }
                if seen.insert(text.clone()) {
                    skills.push(text);
                }
            }
            value["skills"] = json!(skills);
            let now: DateTime<Utc> = std::time::SystemTime::now().into();
            if let Some(posted) = value["posted_at"].as_str() {
                if DateTime::parse_from_rfc3339(posted).map_err(|_| request_error())?
                    > now + chrono::Duration::minutes(5)
                    || !value["posted_date"].is_null()
                {
                    return Err(request_error());
                }
            }
            if let Some(posted) = value["posted_date"].as_str()
                && chrono::NaiveDate::parse_from_str(posted, "%Y-%m-%d")
                    .map_err(|_| request_error())?
                    > now.date_naive() + chrono::Duration::days(1)
            {
                return Err(request_error());
            }
            for (lo, hi) in [
                ("experience_min", "experience_max"),
                ("applicants_min", "applicants_max"),
                ("salary_min", "salary_max"),
            ] {
                if let (Some(lo), Some(hi)) = (value[lo].as_f64(), value[hi].as_f64())
                    && lo > hi
                {
                    return Err(request_error());
                }
            }
        }
        Some("NaukriQuestionnaire") => {
            let mut seen = std::collections::HashSet::new();
            let options = value["options"].as_array().ok_or_else(request_error)?;
            for option in options {
                let text = option.as_str().ok_or_else(request_error)?;
                if stripped(text).is_empty() || text.chars().count() > 160 || !seen.insert(text) {
                    return Err(request_error());
                }
            }
            if value["answer_kind"] == "choice" && options.is_empty() {
                return Err(request_error());
            }
        }
        Some("NaukriExecutionObservation") => {
            const FIELDS: &[&str] = &[
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
            if value["profile_fields"]
                .as_object()
                .ok_or_else(request_error)?
                .keys()
                .any(|k| !FIELDS.contains(&k.as_str()))
                || crate::python_json::serialize(&value["profile_fields"], false, true).len()
                    > 65536
            {
                return Err(request_error());
            }
        }
        Some("Intent") => {
            static FILTER: LazyLock<crate::legacy_regex::Regex> =
                LazyLock::new(|| crate::legacy_regex::Regex::new(r"\A[\w .+#&/-]{1,100}\z", false));
            for key in ["company", "role", "location"] {
                if let Some(text) = value[key].as_str()
                    && !FILTER.is_match(text)?
                {
                    return Err(request_error());
                }
            }
            for text in value["skills"].as_array().ok_or_else(request_error)? {
                if !FILTER.is_match(text.as_str().ok_or_else(request_error)?)? {
                    return Err(request_error());
                }
            }
            if (!value["selection"].is_null() || !value["job_id"].is_null())
                && value["category"] != "SHOW_JOB"
                || !value["url"].is_null() && value["category"] != "PREPARE_APPLICATION"
                || value["category"] == "PREPARE_APPLICATION"
                    && value["url"].is_null()
                    && value["company"].is_null()
            {
                return Err(request_error());
            }
        }
        _ => {}
    }
    Ok(())
}
fn encode(
    schema: &Value,
    value: &Value,
    input: &InputOrder,
    model: Option<&str>,
    output: &mut String,
) -> Result<()> {
    let (schema, resolved) = shape(schema, value);
    let model = resolved.or(model);
    match value {
        Value::Object(object) => {
            let mut keys = Vec::new();
            if let Some(fields) = model.and_then(|m| ORDER[m].as_array()) {
                keys.extend(fields.iter().filter_map(Value::as_str).map(str::to_owned));
            } else if let InputOrder::Object(fields) = input {
                keys.extend(fields.iter().map(|(k, _)| k.clone()));
            }
            keys.extend(object.keys().cloned());
            let mut seen = std::collections::HashSet::new();
            let mut comma = false;
            output.push('{');
            for key in keys {
                if !seen.insert(key.clone()) {
                    continue;
                }
                let Some(value) = object.get(&key) else {
                    continue;
                };
                if comma {
                    output.push(',');
                }
                comma = true;
                output.push_str(&serde_json::to_string(&key).map_err(|_| request_error())?);
                output.push(':');
                if model == Some("Command") && key == "profile_secret" && !value.is_null() {
                    output.push_str("\"**********\"");
                    continue;
                }
                let child = if schema["properties"].get(&key).is_some() {
                    &schema["properties"][&key]
                } else {
                    &schema["additionalProperties"]
                };
                encode(child, value, input.field(&key), None, output)?;
            }
            output.push('}');
        }
        Value::Array(array) => {
            output.push('[');
            for (index, value) in array.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                encode(&schema["items"], value, input.item(index), None, output)?;
            }
            output.push(']');
        }
        _ => output.push_str(&serde_json::to_string(value).map_err(|_| request_error())?),
    }
    Ok(())
}
pub(super) fn parse(bytes: &[u8]) -> Result<(Value, String)> {
    if bytes.len() > 1024 * 1024 {
        return Err(request_error());
    }
    let mut value: Value = serde_json::from_slice(bytes).map_err(|_| request_error())?;
    if !VALIDATOR.is_valid(&value) {
        return Err(request_error());
    }
    if value.get("request_id").is_none() {
        value["request_id"] = json!(Uuid::new_v4());
    }
    normalize(&SCHEMA, &mut value)?;
    if !value["inspection"].is_null() {
        value["inspection"] =
            forms::normalize(forms::Kind::Inspection, value["inspection"].clone())?;
    }
    if !value["receipt"].is_null() {
        value["receipt"] = forms::normalize(forms::Kind::Receipt, value["receipt"].clone())?;
    }
    if !VALIDATOR.is_valid(&value) {
        return Err(request_error());
    }
    let input: InputOrder = serde_json::from_slice(bytes).map_err(|_| request_error())?;
    let mut encoded = String::new();
    encode(&SCHEMA, &value, &input, Some("Command"), &mut encoded)?;
    Ok((value, format!("{:x}", Sha256::digest(encoded.as_bytes()))))
}
/// Hash-only oracle surface. It returns no normalized command, secret or candidate text.
pub fn payload_hash(bytes: &[u8]) -> Result<String> {
    parse(bytes).map(|(_, hash)| hash)
}
