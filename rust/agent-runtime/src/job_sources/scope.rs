//! Pure owner request/profile scope; no grant, provider call, local ingestion or candidate-data output.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::sync::LazyLock;
use uuid::Uuid;
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn contract() -> &'static Contract {
    static CONTRACT: LazyLock<Contract> = LazyLock::new(|| {
        let schema: Value =
            serde_json::from_str(include_str!("../../schemas/discovery-run-request.json"))
                .expect("actual discovery run schema");
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("discovery run DTO");
        Contract { schema, validator }
    });
    &CONTRACT
}
fn invalid() -> Failure {
    Failure("invalid_discovery_run_request")
}
pub fn normalize(mut value: Value) -> Result<Value> {
    if value.to_string().len() > 4194304 {
        return Err(Failure("discovery_run_request_limit"));
    }
    let contract = contract();
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for (key, p) in contract.schema["properties"]
        .as_object()
        .expect("run fields")
    {
        if let Some(default) = p.get("default") {
            fields.entry(key.clone()).or_insert(default.clone());
        }
    }
    fields.entry("query").or_insert(json!({}));
    fields.entry("manual_jobs").or_insert(json!([]));
    for key in ["allow_paid", "use_profile"] {
        if let Some(value) = fields.get_mut(key) {
            *value = crate::resource_contract::boolean(value).map_err(|_| invalid())?;
        }
    }
    let query = super::contract::query(fields.get("query").cloned().ok_or_else(invalid)?)?;
    fields.insert("query".into(), query);
    if !contract.validator.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
pub fn request_hash(request: &Value) -> Result<String> {
    let mut request = normalize(request.clone())?;
    request
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("idempotency_key");
    Ok(crate::startup_catalog::identity::content_hash(&request))
}
pub fn effective_query(explicit: &Value, profile: Option<&Value>) -> Result<Value> {
    let mut query = super::contract::query(explicit.clone())?;
    let Some(profile) = profile else {
        return Ok(query);
    };
    let prefs = &profile["preferences"];
    for (key, preference) in [
        ("keywords", "target_titles"),
        ("locations", "preferred_locations"),
    ] {
        if query[key].as_array().is_some_and(|a| a.is_empty()) {
            let terms = prefs[preference]
                .as_array()
                .ok_or(Failure("invalid_discovery_profile_scope"))?
                .iter()
                .take(10)
                .cloned()
                .collect::<Vec<_>>();
            query[key] = json!(terms);
        }
    }
    if query["remote_preference"].is_null() {
        query["remote_preference"] = prefs["remote_preference"].clone();
    }
    if query["employment_types"]
        .as_array()
        .is_some_and(|a| a.is_empty())
    {
        query["employment_types"] = prefs["employment_types"].clone();
    }
    super::contract::query(query).map_err(|_| Failure("invalid_discovery_profile_scope"))
}
pub fn profile_pin(profile: Option<&Value>) -> Result<Value> {
    let Some(profile) = profile else {
        return Ok(Value::Null);
    };
    if !profile.is_object() || profile.to_string().len() > 262144 {
        return Err(Failure("invalid_discovery_profile_scope"));
    }
    let id = profile["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .filter(|id| !id.is_nil())
        .ok_or(Failure("invalid_discovery_profile_scope"))?;
    let version = profile["version"]
        .as_i64()
        .filter(|n| *n > 0 && *n <= i32::MAX as i64)
        .ok_or(Failure("invalid_discovery_profile_scope"))?;
    Ok(json!({"id":id,"version":version,"content_hash":crate::python_json::digest(profile)}))
}
/// Private scope for an original public run. Returning a scope does not authorize its execution.
pub fn build(request: Value, profile: Option<&Value>) -> Result<Value> {
    let request = normalize(request)?;
    let source = super::plan::Source::parse(request["source"].as_str().ok_or_else(invalid)?)?;
    if request["manual_jobs"]
        .as_array()
        .is_none_or(|a| !a.is_empty())
    {
        return Err(Failure("public_job_manual_source_required"));
    }
    let profile = if request["use_profile"] == true {
        profile
    } else {
        None
    };
    let effective = effective_query(&request["query"], profile)?;
    let pin = profile_pin(profile)?;
    Ok(
        json!({"schema":1,"source":source.name(),"request_hash":request_hash(&request)?,"explicit_query":request["query"],"effective_query":effective,"use_profile":request["use_profile"],"profile_pin":pin,"allow_paid":request["allow_paid"],"provider_calls":0,"writes":0,"execution_authorized":false}),
    )
}
