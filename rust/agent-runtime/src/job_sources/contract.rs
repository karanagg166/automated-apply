//! Actual job/query DTO semantics; pure normalization performs no URL fetch or provider operation.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::sync::LazyLock;
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(raw: &str) -> Contract {
    let schema: Value = serde_json::from_str(raw).expect("frozen public job contract");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(false)
        .build(&schema)
        .expect("public job schema");
    Contract { schema, validator }
}
fn job() -> &'static Contract {
    static JOB: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/normalized-job.json")));
    &JOB
}
fn invalid() -> Failure {
    Failure("invalid_normalized_job")
}
fn stamp(value: &Value, now: DateTime<Utc>) -> Result<Value> {
    let raw = crate::packet_record::timestamp(value, true).map_err(|_| invalid())?;
    let at = crate::packet_record::expiry(&raw)
        .map_err(|_| invalid())?
        .ok_or_else(invalid)?;
    let earliest = DateTime::parse_from_rfc3339("1990-01-01T00:00:00Z")
        .expect("fixed date")
        .to_utc();
    if at < earliest || at > now + chrono::Duration::days(1) {
        return Err(invalid());
    }
    Ok(json!(at.to_rfc3339_opts(
        if at.timestamp_subsec_micros() == 0 {
            chrono::SecondsFormat::Secs
        } else {
            chrono::SecondsFormat::Micros
        },
        true
    )))
}
pub fn normalize(value: Value, now: DateTime<Utc>) -> Result<Value> {
    if value.to_string().len() > 1048576 {
        return Err(Failure("normalized_job_input_limit"));
    }
    let contract = job();
    let input = value.as_object().ok_or_else(invalid)?;
    let mut fields = serde_json::Map::new();
    for (key, p) in contract.schema["properties"]
        .as_object()
        .expect("job fields")
    {
        if let Some(v) = input.get(key) {
            fields.insert(key.clone(), v.clone());
        } else if let Some(v) = p.get("default") {
            fields.insert(key.clone(), v.clone());
        } else if p["type"] == "array" {
            fields.insert(key.clone(), json!([]));
        } else if p["type"] == "object" {
            fields.insert(key.clone(), json!({}));
        } else if ["first_observed_date", "last_observed_date", "retrieved_at"]
            .contains(&key.as_str())
        {
            fields.insert(key.clone(), stamp(&json!(now.to_rfc3339()), now)?);
        }
    }
    for (key, value) in fields.iter_mut() {
        let p = &contract.schema["properties"][key];
        let string = p["type"] == "string"
            || p["anyOf"]
                .as_array()
                .is_some_and(|a| a.iter().any(|s| s["type"] == "string"));
        if string
            && ![
                "date_posted",
                "first_observed_date",
                "last_observed_date",
                "retrieved_at",
                "remote_type",
                "salary_period",
                "source_verification_status",
            ]
            .contains(&key.as_str())
        {
            if let Value::String(s) = value {
                *s = s.trim().into();
            }
        }
    }
    for key in ["skills_required", "skills_preferred", "quality_flags"] {
        if let Some(Value::Array(items)) = fields.get_mut(key) {
            for value in items {
                if let Value::String(s) = value {
                    *s = s.trim().into();
                }
            }
        }
    }
    for key in ["is_remote", "is_confirmed_current"] {
        if let Some(v) = fields.get_mut(key) {
            if !v.is_null() {
                *v = crate::resource_contract::boolean(v).map_err(|_| invalid())?;
            }
        }
    }
    if fields
        .get("remote_type")
        .is_some_and(|v| v.is_null() || v == "unspecified")
    {
        fields.insert("remote_type".into(), json!("unknown"));
    }
    for key in [
        "experience_min_years",
        "experience_max_years",
        "salary_min",
        "salary_max",
    ] {
        if let Some(v) = fields.get_mut(key) {
            if !v.is_null() {
                let experience = key.starts_with("experience_");
                if experience && !v.is_number() {
                    return Err(invalid());
                }
                *v = crate::profile_contract::number(
                    &json!({"type":"number","minimum":0,"maximum":if experience{60.0}else{1e12}}),
                    v.clone(),
                )
                .map_err(|_| invalid())?;
            }
        }
    }
    for key in [
        "date_posted",
        "first_observed_date",
        "last_observed_date",
        "retrieved_at",
    ] {
        if let Some(v) = fields.get_mut(key) {
            if !v.is_null() {
                *v = stamp(v, now)?;
            }
        }
    }
    if let Some(Value::String(host)) = fields.get_mut("company_domain") {
        *host = host
            .to_lowercase()
            .trim_matches(crate::context_contract::python_space)
            .trim_end_matches('.')
            .into();
        static HOST: LazyLock<regex::Regex> =
            LazyLock::new(|| regex::Regex::new(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$").unwrap());
        if !HOST.is_match(host) {
            return Err(invalid());
        }
        crate::job_urls::canonical(&format!("https://{host}")).map_err(|_| invalid())?;
    }
    if let Some(Value::String(currency)) = fields.get("salary_currency") {
        static CURRENCY: LazyLock<regex::Regex> =
            LazyLock::new(|| regex::Regex::new(r"^(?:[A-Z]{3}|[$€£])$").unwrap());
        if !CURRENCY.is_match(currency) {
            return Err(invalid());
        }
    }
    if let Some(intelligence) = fields.get("company_intelligence") {
        let intel = intelligence.as_object().ok_or_else(invalid)?;
        for key in [
            "stage",
            "batch",
            "remote_policy",
            "source",
            "verification_status",
        ] {
            if intel
                .get(key)
                .is_some_and(|v| !v.as_str().is_some_and(|s| s.chars().count() <= 200))
            {
                return Err(invalid());
            }
        }
        if intel.get("technologies").is_some_and(|v| {
            !v.as_array().is_some_and(|a| {
                a.len() <= 100
                    && a.iter()
                        .all(|v| v.as_str().is_some_and(|s| s.chars().count() <= 200))
            })
        }) {
            return Err(invalid());
        }
    }
    let mut out = Value::Object(fields);
    if !contract.validator.is_valid(&out) {
        return Err(invalid());
    }
    for (min, max) in [
        ("experience_min_years", "experience_max_years"),
        ("salary_min", "salary_max"),
    ] {
        if out[min]
            .as_f64()
            .zip(out[max].as_f64())
            .is_some_and(|(a, b)| a > b)
        {
            return Err(invalid());
        }
    }
    let url = |key: &str| -> Result<Option<String>> {
        if out[key].is_null() {
            Ok(None)
        } else {
            crate::job_urls::canonical(out[key].as_str().ok_or_else(invalid)?)
                .map(Some)
                .map_err(|_| invalid())
        }
    };
    let original = url("original_url")?.ok_or_else(invalid)?;
    let supplied = url("canonical_url")?;
    url("application_url")?;
    let application =
        crate::job_urls::ats(out["application_url"].as_str()).map_err(|_| invalid())?;
    if supplied
        .as_ref()
        .is_some_and(|s| s != &original && application.as_ref() != Some(s))
    {
        return Err(invalid());
    }
    out["canonical_url"] = json!(application.unwrap_or(original));
    if out["remote_type"] == "unknown" && out["is_remote"] == true {
        out["remote_type"] = json!("remote");
    }
    out["is_remote"] = match out["remote_type"].as_str() {
        Some("remote") => json!(true),
        Some("onsite") => json!(false),
        _ => Value::Null,
    };
    if out["company_name"].is_null() || out["company_name"] == "" {
        out["company_name"] = Value::Null;
        let flags = out["quality_flags"]
            .as_array_mut()
            .expect("validated flags");
        if !flags.iter().any(|v| v == "company_unknown") {
            flags.push(json!("company_unknown"));
        }
    }
    let first = crate::packet_record::expiry(&out["first_observed_date"])
        .map_err(|_| invalid())?
        .ok_or_else(invalid)?;
    let last = crate::packet_record::expiry(&out["last_observed_date"])
        .map_err(|_| invalid())?
        .ok_or_else(invalid)?;
    if last < first {
        out["first_observed_date"] = out["last_observed_date"].clone();
    }
    if serde_json::to_vec(&out).map_err(|_| invalid())?.len() > 262144 {
        return Err(Failure("normalized_job_record_limit"));
    }
    Ok(out)
}
pub fn query(mut value: Value) -> Result<Value> {
    static QUERY: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/discovery-query.json")));
    let fields = value
        .as_object_mut()
        .ok_or(Failure("invalid_discovery_query"))?;
    for (key, p) in QUERY.schema["properties"]
        .as_object()
        .expect("query fields")
    {
        if let Some(default) = p.get("default") {
            fields.entry(key.clone()).or_insert(default.clone());
        } else if p["type"] == "array" {
            fields.entry(key.clone()).or_insert(json!([]));
        }
    }
    for key in ["keywords", "locations"] {
        if let Some(Value::Array(a)) = fields.get_mut(key) {
            for v in a {
                if let Value::String(s) = v {
                    *s = s.trim().into();
                }
            }
        }
    }
    for (key, min, max) in [
        ("page", 1, 100),
        ("limit", 1, 100),
        ("max_age_days", 1, 3650),
    ] {
        if let Some(v) = fields.get_mut(key) {
            if !v.is_null() {
                *v = json!(
                    crate::profile_contract::pagination_integer(v.clone(), min, max)
                        .map_err(|_| Failure("invalid_discovery_query"))?
                );
            }
        }
    }
    if !QUERY.validator.is_valid(&value) {
        return Err(Failure("invalid_discovery_query"));
    }
    Ok(value)
}
