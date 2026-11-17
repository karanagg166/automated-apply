//! Existing search preference DTO only; matching never grants application eligibility.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::sync::LazyLock;
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn contract() -> &'static Contract {
    static VALUE: LazyLock<Contract> = LazyLock::new(|| {
        let schema: Value =
            serde_json::from_str(include_str!("../../schemas/conversation-preferences.json"))
                .expect("frozen search preferences");
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("search preference validator");
        Contract { schema, validator }
    });
    &VALUE
}
fn invalid() -> Failure {
    Failure("invalid_conversation_preferences")
}
pub fn normalize(mut input: Value) -> Result<Value> {
    if input.to_string().len() > 65536 {
        return Err(invalid());
    }
    let fields = input.as_object_mut().ok_or_else(invalid)?;
    for key in ["saved_jobs_only"] {
        if let Some(value) = fields.get_mut(key) {
            *value = crate::resource_contract::boolean(value).map_err(|_| invalid())?;
        }
    }
    for key in ["require_known_properties", "duplicate_prevention"] {
        if let Some(value) = fields.get(key) {
            if value != true && value.as_u64() != Some(1) {
                return Err(invalid());
            }
        }
        if fields.contains_key(key) {
            fields.insert(key.into(), json!(true));
        }
    }
    let c = contract();
    let value =
        crate::profile_contract::normalize_shape(&c.schema, input).map_err(|_| invalid())?;
    if !c.validator.is_valid(&value) {
        return Err(invalid());
    }
    for (low, high) in [
        ("minimum_experience", "maximum_experience"),
        ("minimum_salary", "maximum_salary"),
        ("minimum_employees", "maximum_employees"),
    ] {
        if let (Some(a), Some(b)) = (value[low].as_f64(), value[high].as_f64()) {
            if a > b {
                return Err(invalid());
            }
        }
    }
    if value["source_platforms"].as_array().is_none_or(|a| {
        a.iter().any(|s| {
            s.as_str()
                .is_none_or(|s| !(1..=100).contains(&s.chars().count()))
        })
    }) {
        return Err(invalid());
    }
    Ok(value)
}
