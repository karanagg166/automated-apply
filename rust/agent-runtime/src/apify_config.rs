//! Reviewed actor inputs/cost prerequisites only. No account probe or execution permission.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::sync::LazyLock;
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn contract() -> &'static Contract {
    static CONTRACT: LazyLock<Contract> = LazyLock::new(|| {
        let schema: Value =
            serde_json::from_str(include_str!("../schemas/apify-actor-configuration.json"))
                .expect("frozen Apify actor DTO");
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("actor schema");
        Contract { schema, validator }
    });
    &CONTRACT
}
fn invalid() -> Failure {
    Failure("invalid_apify_actor_configuration")
}
pub fn normalize(mut value: Value) -> Result<Value> {
    if value.to_string().len() > 65536 {
        return Err(Failure("apify_actor_input_limit"));
    }
    let contract = contract();
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for (key, p) in contract.schema["properties"]
        .as_object()
        .expect("actor properties")
    {
        if let Some(default) = p.get("default") {
            fields.entry(key.clone()).or_insert(default.clone());
        }
    }
    fields.entry("fixed_input").or_insert(json!({}));
    for key in [
        "enabled",
        "reviewed",
        "platform_usage_included",
        "account_spending_limit_verified",
    ] {
        if let Some(v) = fields.get_mut(key) {
            *v = crate::resource_contract::boolean(v).map_err(|_| invalid())?;
        }
    }
    for key in [
        "schema_evidence_url",
        "pricing_evidence_url",
        "permission_evidence_url",
    ] {
        if let Some(v) = fields.get_mut(key) {
            *v = json!(
                v.as_str()
                    .and_then(crate::resources::public_https)
                    .ok_or_else(invalid)?
            );
        }
    }
    for key in ["estimated_per_item_usd", "estimated_start_usd"] {
        if let Some(v) = fields.get_mut(key) {
            *v = crate::profile_contract::number(
                &json!({"type":"number","minimum":0,"maximum":100}),
                v.clone(),
            )
            .map_err(|_| invalid())?;
        }
    }
    if let Some(v) = fields.get_mut("review_expires_at") {
        if !v.is_null() {
            *v = crate::packet_record::timestamp(v, false).map_err(|_| invalid())?;
        }
    }
    if !contract.validator.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
pub fn safe_actor(value: &str) -> Result<String> {
    static ACTOR: LazyLock<regex::Regex> =
        LazyLock::new(|| regex::Regex::new(r"^[A-Za-z0-9_-]+(?:[~/][A-Za-z0-9_-]+)?$").unwrap());
    if value.len() > 200 || !ACTOR.is_match(value) {
        return Err(Failure("apify_actor_id_invalid"));
    }
    Ok(value.replace('/', "~"))
}
pub fn execution_input_allowed(actor: &str, input: &Value) -> Result<()> {
    safe_actor(actor)?;
    if input.to_string().len() > 65536 {
        return Err(Failure("apify_actor_input_limit"));
    }
    static DENIED: LazyLock<crate::legacy_regex::Regex> = LazyLock::new(|| {
        crate::legacy_regex::Regex::new(
            r"cookie|password|session|chrome.?profile|li_at|csrf|access.?token|linkedin",
            true,
        )
    });
    if DENIED.is_match(actor)?
        || DENIED.is_match(&crate::python_json::serialize(input, false, true))?
    {
        return Err(Failure("apify_collection_method_not_authorized"));
    }
    Ok(())
}
pub fn build_input(actor: &Value, query: &Value) -> Result<Value> {
    let fields = actor["field_map"].as_object().ok_or_else(invalid)?;
    if !fields.contains_key("limit") {
        return Err(Failure("apify_unique_bounded_limit_mapping_required"));
    }
    let mapped = fields
        .values()
        .map(|v| v.as_str().ok_or_else(invalid))
        .collect::<Result<std::collections::BTreeSet<_>>>()?;
    if mapped.len() != fields.len() {
        return Err(Failure("apify_unique_bounded_limit_mapping_required"));
    }
    let labels = |v: &Value| -> Result<Vec<String>> {
        v.as_array()
            .filter(|a| a.len() <= 10)
            .ok_or_else(invalid)?
            .iter()
            .map(|v| {
                v.as_str()
                    .filter(|s| s.chars().count() <= 200)
                    .map(String::from)
                    .ok_or_else(invalid)
            })
            .collect()
    };
    let keywords = labels(&query["keywords"])?;
    let locations = labels(&query["locations"])?;
    let limit = query["limit"]
        .as_u64()
        .filter(|n| (1..=100).contains(n))
        .ok_or_else(invalid)?;
    let values = json!({"query":keywords.join(" "),"keywords":keywords,"location":locations.join(", "),"locations":locations,"limit":limit});
    let mut output = actor["fixed_input"]
        .as_object()
        .ok_or_else(invalid)?
        .clone();
    for (key, field) in fields {
        if !matches!(
            key.as_str(),
            "query" | "keywords" | "location" | "locations" | "limit"
        ) {
            return Err(invalid());
        }
        output.insert(
            field.as_str().ok_or_else(invalid)?.to_owned(),
            values[key].clone(),
        );
    }
    let output = Value::Object(output);
    if output.to_string().len() > 65536 {
        return Err(Failure("apify_actor_input_limit"));
    }
    Ok(output)
}
pub fn preflight(
    value: Value,
    credential_present: bool,
    monthly: f64,
    per_run: f64,
    now: DateTime<Utc>,
) -> Result<Value> {
    if !monthly.is_finite()
        || !per_run.is_finite()
        || monthly < 0.0
        || !(0.0..=100.0).contains(&per_run)
    {
        return Err(Failure("invalid_apify_budget_configuration"));
    }
    let actor = normalize(value)?;
    let mut blockers = Vec::new();
    if !credential_present {
        blockers.push("apify_local_token_not_configured");
    }
    if actor["enabled"] != true || actor["reviewed"] != true {
        blockers.push("apify_actor_review_or_enablement_required");
    }
    let expiry = crate::packet_record::expiry(&actor["review_expires_at"]);
    if !expiry
        .is_ok_and(|at| at.is_some_and(|at| at > now && at <= now + chrono::Duration::days(1)))
    {
        blockers.push("apify_actor_review_expired_or_missing");
    }
    if actor["platform_usage_included"] != true || actor["account_spending_limit_verified"] != true
    {
        blockers.push("apify_inclusive_account_hard_cap_review_required");
    }
    if per_run <= 0.0 || monthly < per_run {
        blockers.push("apify_positive_bounded_budget_required");
    }
    let input = build_input(&actor, &json!({"keywords":[],"locations":[],"limit":20}));
    if let Err(e) = input {
        blockers.push(e.0);
    }
    if let Err(e) = execution_input_allowed(
        actor["actor_id"].as_str().ok_or_else(invalid)?,
        &actor["fixed_input"],
    ) {
        blockers.push(e.0);
    }
    Ok(
        json!({"configuration_review_ready":blockers.is_empty(),"blockers":blockers,"credential_configured":credential_present,"live_verified":false,"dispatch_authorized":false,"pricing_basis":"saved_owner_review_not_current_provider_probe","per_run_cap_usd":per_run,"monthly_cap_usd":monthly}),
    )
}
