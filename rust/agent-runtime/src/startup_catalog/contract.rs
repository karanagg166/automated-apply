//! Actual filter and shortlist DTOs; repeated-list GET fields retain their submitted order.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::sync::LazyLock;
use uuid::Uuid;
#[derive(Clone, Copy)]
pub enum Kind {
    Filters,
    Shortlist,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn invalid() -> Failure {
    Failure("invalid_startup_contract")
}
fn contract(kind: Kind) -> &'static Contract {
    fn compile(raw: &str) -> Contract {
        let schema: Value = serde_json::from_str(raw).expect("frozen startup contract");
        let validator = jsonschema::draft202012::options()
            .build(&schema)
            .expect("startup schema");
        Contract { schema, validator }
    }
    static FILTERS: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/startup-filters.json")));
    static SHORTLIST: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/startup-shortlist.json")));
    match kind {
        Kind::Filters => &FILTERS,
        Kind::Shortlist => &SHORTLIST,
    }
}
const LISTS: &[&str] = &[
    "industries",
    "size_bands",
    "locations",
    "roles",
    "skills",
    "stages",
];
pub fn normalize(kind: Kind, mut value: Value) -> Result<Value> {
    let contract = contract(kind);
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for (key, property) in contract.schema["properties"]
        .as_object()
        .expect("startup properties")
    {
        if let Some(default) = property.get("default") {
            fields.entry(key.clone()).or_insert(default.clone());
        } else if LISTS.contains(&key.as_str()) {
            fields.entry(key.clone()).or_insert(json!([]));
        }
    }
    if matches!(kind, Kind::Filters) {
        for key in ["country", "yc_batch", "source"] {
            if let Some(Value::String(s)) = fields.get_mut(key) {
                *s = s
                    .trim_matches(crate::context_contract::python_space)
                    .to_owned();
            }
        }
        for key in LISTS.iter().filter(|k| **k != "size_bands") {
            if let Some(Value::Array(values)) = fields.get_mut(*key) {
                for value in values {
                    if let Value::String(s) = value {
                        *s = s
                            .trim_matches(crate::context_contract::python_space)
                            .to_owned();
                    }
                }
            }
        }
        for key in [
            "has_technical_staff",
            "exact_employee_count",
            "has_business_email",
            "verified_yc",
            "early_stage",
            "include_unknown_size",
            "has_leader_evidence",
            "use_profile",
        ] {
            if let Some(v) = fields.get_mut(key) {
                *v = crate::resource_contract::boolean(v).map_err(|_| invalid())?;
            }
        }
        for (key, min, max) in [
            ("min_employees", 1, 10000000),
            ("max_employees", 1, 10000000),
            ("freshness_days", 1, 365),
            ("page", 1, 250),
            ("limit", 1, 100),
        ] {
            if let Some(v) = fields.get_mut(key) {
                if !v.is_null() {
                    *v = json!(
                        crate::profile_contract::pagination_integer(v.clone(), min, max)
                            .map_err(|_| invalid())?
                    );
                }
            }
        }
        if let Some(v) = fields.get_mut("minimum_score") {
            *v = crate::profile_contract::number(
                &json!({"type":"number","minimum":0,"maximum":100}),
                v.clone(),
            )
            .map_err(|_| invalid())?;
        }
        if let Some(v) = fields.get_mut("observed_after") {
            if !v.is_null() {
                *v = crate::packet_record::timestamp(v, false).map_err(|_| invalid())?;
            }
        }
        if fields
            .get("min_employees")
            .and_then(Value::as_i64)
            .zip(fields.get("max_employees").and_then(Value::as_i64))
            .is_some_and(|(min, max)| min > max)
        {
            return Err(invalid());
        }
    } else if let Some(Value::String(s)) = fields.get_mut("run_id") {
        *s = s.parse::<Uuid>().map_err(|_| invalid())?.to_string();
    }
    if !contract.validator.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
pub fn query(raw: Option<&str>) -> Result<Value> {
    let mut value = json!({});
    let fields = value.as_object_mut().unwrap();
    if let Some(raw) = raw {
        if raw.len() > 16384 {
            return Err(Failure("invalid_startup_query"));
        }
        let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{raw}"))
            .map_err(|_| Failure("invalid_startup_query"))?;
        for (key, text) in url.query_pairs() {
            if LISTS.contains(&key.as_ref()) {
                fields
                    .entry(key.to_string())
                    .or_insert(json!([]))
                    .as_array_mut()
                    .ok_or_else(invalid)?
                    .push(json!(text));
            } else if fields.insert(key.to_string(), json!(text)).is_some() {
                return Err(Failure("invalid_startup_query"));
            }
        }
    }
    normalize(Kind::Filters, value)
}
