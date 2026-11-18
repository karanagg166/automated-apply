//! Actual bounded draft DTOs. Editing preserves omission and rejects explicit null.
use super::*;
use std::sync::LazyLock;
#[derive(Clone, Copy)]
pub enum Kind {
    Input,
    Edit,
    Decision,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn schema(kind: Kind) -> &'static Contract {
    fn compile(raw: &str) -> Contract {
        let schema: Value = serde_json::from_str(raw).expect("frozen outreach contract");
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(true)
            .build(&schema)
            .expect("outreach schema");
        Contract { schema, validator }
    }
    static INPUT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/outreach-input.json")));
    static EDIT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/outreach-edit.json")));
    static DECISION: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/outreach-decision.json")));
    match kind {
        Kind::Input => &INPUT,
        Kind::Edit => &EDIT,
        Kind::Decision => &DECISION,
    }
}
fn invalid_input() -> Failure {
    Failure("invalid_outreach_contract")
}
pub fn normalize(kind: Kind, mut value: Value) -> Result<Value> {
    let contract = schema(kind);
    let object = value.as_object_mut().ok_or_else(invalid_input)?;
    let original = object
        .keys()
        .cloned()
        .collect::<std::collections::BTreeSet<_>>();
    if matches!(kind, Kind::Input) {
        for (k, p) in contract.schema["properties"]
            .as_object()
            .expect("outreach properties")
        {
            if let Some(default) = p.get("default") {
                object.entry(k.clone()).or_insert(default.clone());
            }
        }
    }
    for key in ["contact_id", "job_id"] {
        if let Some(Value::String(s)) = object.get_mut(key) {
            *s = s.parse::<Uuid>().map_err(|_| invalid_input())?.to_string();
        }
    }
    for key in [
        "personal_instructions",
        "idempotency_key",
        "subject",
        "body",
    ] {
        if let Some(Value::String(s)) = object.get_mut(key) {
            *s = s.trim().to_owned();
        }
    }
    if let Some(v) = object.get_mut("use_llm") {
        *v = crate::resource_contract::boolean(v).map_err(|_| invalid_input())?;
    }
    for (key, min, max) in [
        ("max_length", 400, 5000),
        ("expected_revision", 1, i64::MAX),
    ] {
        if let Some(v) = object.get_mut(key) {
            *v = json!(
                crate::profile_contract::pagination_integer(v.clone(), min, max)
                    .map_err(|_| invalid_input())?
            );
        }
    }
    if let Some(Value::String(s)) = object.get_mut("recipient_email") {
        if s.contains(['\r', '\n']) {
            return Err(invalid_input());
        }
        *s = crate::profile_contract::email(s.trim()).map_err(|_| invalid_input())?;
    }
    if matches!(kind, Kind::Edit) {
        if original.iter().all(|k| k == "expected_revision")
            || original
                .iter()
                .filter(|k| k.as_str() != "expected_revision")
                .any(|k| object.get(k) == Some(&Value::Null))
        {
            return Err(invalid_input());
        }
        for key in ["subject", "recipient_email"] {
            if object
                .get(key)
                .and_then(Value::as_str)
                .is_some_and(|s| s.contains(['\r', '\n']))
            {
                return Err(invalid_input());
            }
        }
    }
    if !contract.validator.is_valid(&value) {
        return Err(invalid_input());
    }
    Ok(value)
}
pub fn page(query: Option<&str>) -> Result<(i64, i64)> {
    let mut limit = 20;
    let mut offset = 0;
    let mut seen = std::collections::BTreeSet::new();
    if let Some(query) = query {
        if query.len() > 1024 {
            return Err(Failure("invalid_outreach_query"));
        }
        let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
            .map_err(|_| Failure("invalid_outreach_query"))?;
        for (key, value) in url.query_pairs() {
            if !seen.insert(key.to_string()) {
                return Err(Failure("invalid_outreach_query"));
            }
            match key.as_ref() {
                "limit" => {
                    limit = crate::profile_contract::pagination_integer(json!(value), 1, 100)
                        .map_err(|_| Failure("invalid_outreach_query"))?
                }
                "offset" => {
                    offset = crate::profile_contract::pagination_integer(json!(value), 0, 100000)
                        .map_err(|_| Failure("invalid_outreach_query"))?
                }
                _ => return Err(Failure("invalid_outreach_query")),
            }
        }
    }
    Ok((limit, offset))
}
