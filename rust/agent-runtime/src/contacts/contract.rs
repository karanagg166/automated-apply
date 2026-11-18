//! Actual correction DTO. Omission and explicit null remain different.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::sync::LazyLock;
fn invalid() -> Failure {
    Failure("invalid_contact_correction")
}
pub fn normalize(mut value: Value) -> Result<Value> {
    static SCHEMA: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
        let schema: Value =
            serde_json::from_str(include_str!("../../schemas/contact-correction.json"))
                .expect("frozen contact schema");
        jsonschema::draft202012::options()
            .should_validate_formats(true)
            .build(&schema)
            .expect("contact schema")
    });
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for key in ["full_name", "role_title"] {
        if let Some(Value::String(text)) = fields.get_mut(key) {
            *text = text.trim().to_owned();
        }
    }
    for key in ["company_id", "verification_evidence_id"] {
        if let Some(Value::String(text)) = fields.get_mut(key) {
            *text = text
                .parse::<uuid::Uuid>()
                .map_err(|_| invalid())?
                .to_string();
        }
    }
    if let Some(item) = fields.get_mut("do_not_contact") {
        let parsed = match item {
            Value::Bool(_) | Value::Null => None,
            Value::Number(n) if n.as_f64() == Some(1.0) => Some(true),
            Value::Number(n) if n.as_f64() == Some(0.0) => Some(false),
            Value::String(s) => match s.to_ascii_lowercase().as_str() {
                "true" | "1" | "yes" | "on" | "y" | "t" => Some(true),
                "false" | "0" | "no" | "off" | "n" | "f" => Some(false),
                _ => return Err(invalid()),
            },
            _ => return Err(invalid()),
        };
        if let Some(boolean) = parsed {
            *item = json!(boolean);
        }
    }
    if !SCHEMA.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
