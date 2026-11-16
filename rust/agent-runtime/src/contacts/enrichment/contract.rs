//! Actual bounded EnrichInput normalization; a preview never consumes authorization.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::sync::LazyLock;
fn invalid() -> Failure {
    Failure("invalid_contact_enrichment")
}
pub fn normalize(mut value: Value) -> Result<Value> {
    static SCHEMA: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
        let value: Value =
            serde_json::from_str(include_str!("../../../schemas/contact-enrichment.json"))
                .expect("frozen enrichment schema");
        jsonschema::draft202012::options()
            .build(&value)
            .expect("enrichment schema")
    });
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for (key, default) in [
        ("target_roles", json!([])),
        ("max_people", json!(5)),
        ("providers", json!(["apollo"])),
        ("allow_paid", json!(false)),
        ("allow_fallback", json!(false)),
        ("include_candidates", json!(false)),
        ("idempotency_key", Value::Null),
    ] {
        fields.entry(key).or_insert(default);
    }
    for key in ["allow_paid", "allow_fallback", "include_candidates"] {
        let v = fields.get_mut(key).unwrap();
        *v = match v {
            Value::Bool(v) => json!(v),
            Value::Number(n) if n.as_f64() == Some(1.0) => json!(true),
            Value::Number(n) if n.as_f64() == Some(0.0) => json!(false),
            Value::String(s) => match s.to_ascii_lowercase().as_str() {
                "true" | "1" | "yes" | "on" | "y" | "t" => json!(true),
                "false" | "0" | "no" | "off" | "n" | "f" => json!(false),
                _ => return Err(invalid()),
            },
            _ => return Err(invalid()),
        };
    }
    fields.insert(
        "max_people".into(),
        json!(
            crate::profile_contract::pagination_integer(fields["max_people"].clone(), 1, 25)
                .map_err(|_| invalid())?
        ),
    );
    if let Some(roles) = fields.get_mut("target_roles").and_then(Value::as_array_mut) {
        for role in roles {
            if let Some(text) = role.as_str() {
                *role = json!(text.trim_matches(crate::context_contract::python_space));
            }
        }
    }
    if !SCHEMA.is_valid(&value) {
        return Err(invalid());
    }
    let providers = value["providers"].as_array().unwrap();
    if providers.len() == 2 && providers[0] == providers[1] {
        return Err(invalid());
    }
    Ok(value)
}
