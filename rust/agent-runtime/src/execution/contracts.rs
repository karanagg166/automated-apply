//! Frozen private execution contracts. Reading saved policy never enables work or resets caps.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::sync::LazyLock;

#[derive(Clone, Copy)]
pub enum Kind {
    Policy,
    PolicyUpdate,
    Control,
    Configuration,
    ExecutionControl,
    Start,
    QuestionAnswer,
    AutomationPolicy,
    AutomationPolicyUpdate,
    AutomationControl,
    ImportBatch,
    AccountApproval,
    SyncPolicy,
    SyncPolicyUpdate,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(raw: &str) -> Contract {
    let schema: Value = serde_json::from_str(raw).expect("frozen execution schema");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(true)
        .build(&schema)
        .expect("execution schema");
    Contract { schema, validator }
}
fn contract(kind: Kind) -> &'static Contract {
    static POLICY: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/application-queue-policy.json")));
    static UPDATE: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../schemas/application-queue-policy-update.json"
        ))
    });
    static CONTROL: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/application-queue-control.json")));
    static CONFIG: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/execution-configuration.json")));
    static EXEC_CONTROL: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/execution-control.json")));
    static START: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/execution-start.json")));
    static QUESTION: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/execution-question-answer.json")));
    static AUTOMATION: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../schemas/execution-automation-policy.json"
        ))
    });
    static AUTOMATION_UPDATE: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../schemas/execution-automation-policy-update.json"
        ))
    });
    static AUTOMATION_CONTROL: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../schemas/execution-automation-control.json"
        ))
    });
    static IMPORT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/execution-import-batch.json")));
    static ACCOUNT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/naukri-account-approval.json")));
    static SYNC: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../schemas/naukri-profile-sync-policy.json"
        ))
    });
    static SYNC_UPDATE: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../schemas/naukri-profile-sync-policy-update.json"
        ))
    });
    match kind {
        Kind::Policy => &POLICY,
        Kind::PolicyUpdate => &UPDATE,
        Kind::Control => &CONTROL,
        Kind::Configuration => &CONFIG,
        Kind::ExecutionControl => &EXEC_CONTROL,
        Kind::Start => &START,
        Kind::QuestionAnswer => &QUESTION,
        Kind::AutomationPolicy => &AUTOMATION,
        Kind::AutomationPolicyUpdate => &AUTOMATION_UPDATE,
        Kind::AutomationControl => &AUTOMATION_CONTROL,
        Kind::ImportBatch => &IMPORT,
        Kind::AccountApproval => &ACCOUNT,
        Kind::SyncPolicy => &SYNC,
        Kind::SyncPolicyUpdate => &SYNC_UPDATE,
    }
}
fn invalid() -> Failure {
    Failure("invalid_execution_contract")
}
fn fill(root: &Value, schema: &Value, name: Option<&str>, value: &mut Value) -> Result<()> {
    // These contracts use only nullable scalar unions. Keep their format and
    // numeric normalization rather than silently skipping it inside anyOf.
    if !value.is_null()
        && let Some(choices) = schema["anyOf"].as_array()
        && choices.len() == 2
        && choices.iter().any(|s| s["type"] == "null")
        && let Some(child) = choices.iter().find(|s| s["type"] != "null")
    {
        return fill(root, child, name, value);
    }
    if let Some(reference) = schema["$ref"].as_str() {
        let definition = reference
            .strip_prefix('#')
            .and_then(|p| root.pointer(p))
            .ok_or_else(invalid)?;
        return fill(root, definition, reference.rsplit('/').next(), value);
    }
    if matches!(schema["type"].as_str(), Some("integer" | "number")) {
        *value = crate::profile_contract::number(schema, value.clone()).map_err(|_| invalid())?;
    }
    if schema["type"] == "boolean" {
        *value = crate::resource_contract::boolean(value).map_err(|_| invalid())?;
    }
    if let Some(properties) = schema["properties"].as_object() {
        let object = value.as_object_mut().ok_or_else(invalid)?;
        for (key, child) in properties {
            if !object.contains_key(key) {
                let factory = match (name, key.as_str()) {
                    (Some("QueuePolicy"), "platforms") => Some(json!({"naukri":{}})),
                    (Some("PlatformQueuePolicy"), "sources") => Some(json!([
                        "approved_gmail_alerts",
                        "saved_verified_job",
                        "naukri_ui_search"
                    ])),
                    (Some("AutomationPolicy"), "permitted_actions") => Some(json!(["PREPARATION"])),
                    _ => None,
                };
                if let Some(default) = child.get("default").cloned().or(factory) {
                    object.insert(key.clone(), default);
                } else if !schema["required"]
                    .as_array()
                    .is_some_and(|r| r.iter().any(|v| v == key))
                {
                    if child["type"] == "array" {
                        object.insert(key.clone(), json!([]));
                    } else if child["$ref"].is_string() {
                        object.insert(key.clone(), json!({}));
                    }
                }
            }
            if let Some(value) = object.get_mut(key) {
                fill(root, child, None, value)?;
            }
        }
    }
    if let Some(object) = value.as_object_mut()
        && let Some(child) = schema.get("additionalProperties").filter(|s| s.is_object())
    {
        for value in object.values_mut() {
            fill(root, child, None, value)?;
        }
    }
    if let Some(values) = value.as_array_mut() {
        if schema["minItems"]
            .as_u64()
            .is_some_and(|n| values.len() < (n as usize))
            || schema["maxItems"]
                .as_u64()
                .is_some_and(|n| values.len() > (n as usize))
        {
            return Err(invalid());
        }
        for value in values {
            fill(root, &schema["items"], None, value)?;
        }
    }
    if schema["type"] == "number"
        && let Some(number) = value.as_f64()
    {
        *value = json!(number);
    }
    if schema["format"] == "uuid" {
        let id = value
            .as_str()
            .and_then(|s| s.parse::<uuid::Uuid>().ok())
            .ok_or_else(invalid)?;
        *value = json!(id);
    }
    if schema["format"] == "uri" && !value.is_null() {
        *value = json!(
            crate::resources::public_https(value.as_str().ok_or_else(invalid)?)
                .ok_or_else(invalid)?
        );
    }
    if name == Some("QuestionAnswer") {
        // Pydantic's strict integer rejects a JSON float even when integral.
        if value["expected_revision"].as_i64().is_none() {
            return Err(invalid());
        }
        let text = value["answer"].as_str().ok_or_else(invalid)?;
        if !(1..=4000).contains(&text.chars().count()) {
            return Err(invalid());
        }
        let text = text.trim_matches(crate::context_contract::python_space);
        if text.is_empty() {
            return Err(invalid());
        }
        value["answer"] = json!(text);
    }
    if name == Some("AutomationPolicy") {
        for key in ["allowed_roles", "allowed_locations", "excluded_companies"] {
            let mut seen = std::collections::HashSet::new();
            let mut out = Vec::new();
            for raw in value[key].as_array().ok_or_else(invalid)? {
                let raw = raw.as_str().ok_or_else(invalid)?;
                let trimmed = raw.trim_matches(crate::context_contract::python_space);
                if raw.chars().count() > 200 || trimmed.is_empty() {
                    return Err(invalid());
                }
                let label = automated_apply_domain::text::folded(trimmed);
                if seen.insert(label.clone()) {
                    out.push(label);
                }
            }
            value[key] = json!(out);
        }
        if value["experience_min"]
            .as_f64()
            .zip(value["experience_max"].as_f64())
            .is_some_and(|(a, b)| a > b)
            || value["source"] == "gmail_job_alerts"
                && (value["gmail_account_id"].is_null() || value["gmail_policy_version"].is_null())
        {
            return Err(invalid());
        }
    }
    if name == Some("ImportJob") {
        for key in ["title", "employer"] {
            let text = value[key].as_str().ok_or_else(invalid)?;
            if !(1..=255).contains(&text.chars().count()) {
                return Err(invalid());
            }
            let text = text.trim_matches(crate::context_contract::python_space);
            if text.is_empty() {
                return Err(invalid());
            }
            value[key] = json!(text);
        }
        for (lo, hi) in [
            ("experience_min", "experience_max"),
            ("salary_min", "salary_max"),
        ] {
            if value[lo]
                .as_f64()
                .zip(value[hi].as_f64())
                .is_some_and(|(a, b)| a > b)
            {
                return Err(invalid());
            }
        }
        for key in ["observed_at", "posted_at"] {
            if !value[key].is_null() {
                let at =
                    chrono::DateTime::parse_from_rfc3339(value[key].as_str().ok_or_else(invalid)?)
                        .map_err(|_| invalid())?;
                if at > chrono::Utc::now() + chrono::Duration::minutes(5) {
                    return Err(invalid());
                }
                value[key] = json!(at.to_rfc3339_opts(
                    if at.timestamp_subsec_micros() == 0 {
                        chrono::SecondsFormat::Secs
                    } else {
                        chrono::SecondsFormat::Micros
                    },
                    true
                ));
            }
        }
        if value["posting_status"] != "unknown" && value["observed_at"].is_null() {
            return Err(invalid());
        }
    }
    if name == Some("QueuePreferences") {
        for key in ["roles", "locations", "excluded_companies"] {
            let mut seen = std::collections::HashSet::new();
            let mut labels = Vec::new();
            for raw in value[key].as_array().ok_or_else(invalid)? {
                let text = raw.as_str().ok_or_else(invalid)?;
                let stripped = text.trim_matches(crate::context_contract::python_space);
                if stripped.is_empty() || text.chars().count() > 200 {
                    return Err(invalid());
                }
                if seen.insert(stripped) {
                    labels.push(stripped.to_owned());
                }
            }
            value[key] = json!(labels);
        }
        for (lo, hi) in [
            ("experience_min", "experience_max"),
            ("minimum_salary", "maximum_salary"),
        ] {
            if let (Some(lo), Some(hi)) = (value[lo].as_f64(), value[hi].as_f64())
                && lo > hi
            {
                return Err(invalid());
            }
        }
    }
    if name == Some("QueuePolicy") {
        if value["platforms"].get("naukri").is_none()
            || value["day_timezone"]
                .as_str()
                .and_then(|s| s.parse::<chrono_tz::Tz>().ok())
                .is_none()
        {
            return Err(invalid());
        }
    }
    Ok(())
}
pub fn normalize(kind: Kind, mut input: Value) -> Result<Value> {
    if matches!(kind, Kind::QuestionAnswer) && input["expected_revision"].as_i64().is_none() {
        return Err(invalid());
    }
    let contract = contract(kind);
    let name = contract.schema["title"].as_str();
    fill(&contract.schema, &contract.schema, name, &mut input)?;
    if !contract.validator.is_valid(&input) {
        return Err(invalid());
    }
    Ok(input)
}
pub fn limits(policy: &Value, platform: &str) -> Result<Value> {
    let local = &policy["platforms"][platform];
    let global = &policy["global_limits"];
    if !local.is_object() || !global.is_object() {
        return Err(invalid());
    }
    let value = |field: &str, mode: &str| {
        if local[mode] == "custom" {
            local["limits"][field].clone()
        } else {
            global[field].clone()
        }
    };
    Ok(
        json!({"daily_cap":value("daily_cap","cap_mode"),"max_job_age_days":value("max_job_age_days","age_mode"),"applicant_limit":value("applicant_limit","applicants_mode"),"unknown_applicants":value("unknown_applicants","applicants_mode"),"minimum_match_score":global["minimum_match_score"]}),
    )
}
pub fn day_bucket(time: chrono::DateTime<chrono::Utc>, zone: &str) -> Result<String> {
    let zone = zone.parse::<chrono_tz::Tz>().map_err(|_| invalid())?;
    Ok(time.with_timezone(&zone).date_naive().to_string())
}
