//! Form observations are untrusted. Only separately reviewed saved plans can authorize exact fields.
use super::*;
use crate::legacy_regex::Regex;
use chrono::NaiveDate;
pub enum Kind {
    Inspection,
    Plan,
    Receipt,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn compile(raw: &str) -> Contract {
    let schema: Value = serde_json::from_str(raw).expect("frozen form contract");
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(true)
        .build(&schema)
        .expect("form validator");
    Contract { schema, validator }
}
fn contract(kind: Kind) -> &'static Contract {
    static INSPECTION: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/form-inspection.json")));
    static PLAN: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/form-fill-plan.json")));
    static RECEIPT: LazyLock<Contract> =
        LazyLock::new(|| compile(include_str!("../../schemas/form-fill-receipt.json")));
    match kind {
        Kind::Inspection => &INSPECTION,
        Kind::Plan => &PLAN,
        Kind::Receipt => &RECEIPT,
    }
}
fn defaults(root: &Value, schema: &Value, value: &mut Value) {
    if let Some(reference) = schema["$ref"].as_str() {
        if let Some(shape) = reference.strip_prefix('#').and_then(|p| root.pointer(p)) {
            defaults(root, shape, value);
        }
        return;
    }
    if let (Some(props), Some(object)) = (schema["properties"].as_object(), value.as_object_mut()) {
        for (key, shape) in props {
            if !object.contains_key(key)
                && let Some(default) = shape.get("default")
            {
                object.insert(key.clone(), default.clone());
            }
            if !object.contains_key(key)
                && shape["type"] == "array"
                && !schema["required"]
                    .as_array()
                    .is_some_and(|r| r.iter().any(|v| v == key))
            {
                object.insert(key.clone(), json!([]));
            }
            if let Some(item) = object.get_mut(key) {
                defaults(root, shape, item);
            }
        }
    }
    if let (Some(shape), Some(array)) = (schema.get("items"), value.as_array_mut()) {
        for item in array {
            defaults(root, shape, item);
        }
    }
}
pub fn normalize(kind: Kind, mut value: Value) -> Result<Value> {
    if matches!(kind, Kind::Plan)
        && value["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .is_none()
    {
        return Err(Failure("invalid_browser_form_input"));
    }
    let shape = contract(kind);
    defaults(&shape.schema, &shape.schema, &mut value);
    if !shape.validator.is_valid(&value) {
        return Err(Failure("invalid_browser_form_input"));
    }
    let inspection = if value.get("inspection").is_some() {
        &value["inspection"]
    } else {
        &value
    };
    if let Some(fields) = inspection["fields"].as_array() {
        let mut seen = std::collections::HashSet::new();
        if fields
            .iter()
            .any(|f| !seen.insert(f["field_id"].as_str().unwrap_or("")))
        {
            return Err(Failure("invalid_browser_form_input"));
        }
    }
    Ok(value)
}
pub fn manual_only(labels: &[&str]) -> Result<bool> {
    static SENSITIVE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"password|passcode|passphrase|one.?time|\botp\b|\bmfa\b|\b2fa\b|two.?factor|verification.?code|security.?code|credit.?card|debit.?card|card.?number|\bcvv\b|\bcvc\b|card.?expir|name\s+on\s+(?:the\s+)?card|bank.?account|routing.?number|\biban\b|\bifsc\b|\bupi\b|payment|session|token|secret|api.?key|private.?key|social.?security|\bssn\b|\baadhaar\b|\baadhar\b|\bpan\s*(?:card|number|no)\b|tax.?id|national.?id|government.{0,15}\bid\b|passport|driv(?:er|ing).?licen[sc]e|\bpin\b(?![\s-]*code)|security.?question|\b(?:gender|race|ethnic\w*|religion|disabil\w*|veteran|military|sexual\w*|pronouns?|marital|self.?identif\w*)\b|date.?of.?birth|birth.?date|\bdob\b",
            true,
        )
    });
    static ATTESTATION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"\b(?:consent|agree|agreement|terms|privacy|acknowledge|certif(?:y|ication)|attest(?:ation)?|declare|declaration|hereby|gdpr|background\s*check|eeo|nda|subscribe|permission|affirm|accept)\b|true\s+and\s+(?:correct|accurate)|data\s*processing|non.?disclosure|accuracy\s+of\s+information",
            true,
        )
    });
    let text = labels.join(" ").replace(['_', '-'], " ");
    Ok(SENSITIVE.is_match(&text)? || ATTESTATION.is_match(&text)?)
}
pub fn label_permitted(field: &Value, inspection: &Value) -> Result<bool> {
    let text = |key| field[key].as_str().unwrap_or("");
    let mut labels = vec![text("label"), text("group_label"), text("section")];
    let options = field["options"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_input"))?;
    labels.extend(options.iter().filter_map(Value::as_str));
    if labels.iter().take(2).any(|s| s.chars().count() >= 160) || manual_only(&labels)? {
        return Ok(false);
    }
    let repeated = inspection["fields"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_input"))?
        .iter()
        .filter(|other| {
            ["section", "group_label", "label"]
                .iter()
                .all(|key| other[key] == field[key])
        })
        .count()
        > 1;
    Ok(!repeated)
}
pub fn inert_label(label: &str) -> Result<bool> {
    static INJECTION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"ignore.{0,40}instructions|system prompt|developer message|javascript:|execute.{0,20}command|send.{0,30}(?:email|resume)|click.{0,20}(?:submit|apply)",
            true,
        )
    });
    Ok(label.is_empty() || INJECTION.is_match(label)?)
}
pub fn control_value(field: &Value, answer: &str, has_evidence: bool) -> Result<Option<String>> {
    let kind = field["kind"]
        .as_str()
        .ok_or(Failure("invalid_browser_form_input"))?;
    let options = field["options"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_input"))?;
    if answer.is_empty() {
        return Ok(None);
    }
    if matches!(kind, "checkbox" | "radio") {
        return Ok(
            (field["group_label"].as_str().is_some_and(|s| !s.is_empty())
                && has_evidence
                && options
                    .first()
                    .and_then(Value::as_str)
                    .is_some_and(|option| {
                        automated_apply_domain::text::folded(option)
                            == automated_apply_domain::text::folded(answer)
                    }))
            .then(|| "true".into()),
        );
    }
    if kind == "number" {
        static NUMBER: LazyLock<regex::Regex> =
            LazyLock::new(|| regex::Regex::new(r"\A([0-9]+(?:\.[0-9]+)?)(?: years)?\z").unwrap());
        return Ok(NUMBER.captures(answer).map(|c| c[1].to_owned()));
    }
    if kind == "email" {
        static EMAIL: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"\A[^@\s]+@[^@\s]+\.[^@\s]+\z", false));
        if !EMAIL.is_match(answer)? {
            return Ok(None);
        }
    }
    if kind == "url" && crate::resources::public_https(answer).is_none() {
        return Ok(None);
    }
    if matches!(kind, "date" | "month") {
        let length = if kind == "date" { 10 } else { 7 };
        if answer.len() != length
            || answer.starts_with("0000")
            || !answer.bytes().enumerate().all(|(i, b)| {
                if i == 4 || i == 7 {
                    b == b'-'
                } else {
                    b.is_ascii_digit()
                }
            })
        {
            return Ok(None);
        }
        let date = if kind == "date" {
            answer.to_owned()
        } else {
            format!("{answer}-01")
        };
        if NaiveDate::parse_from_str(&date, "%Y-%m-%d").is_err() {
            return Ok(None);
        }
    }
    if kind == "select" && !options.iter().any(|v| v == answer) {
        return Ok(None);
    }
    Ok(Some(answer.to_owned()))
}
pub fn receipt_status(plan: &Value, receipt: &Value) -> Result<&'static str> {
    if plan["state"] == "finished" {
        return Ok("already_recorded");
    }
    let results = receipt["results"]
        .as_array()
        .ok_or(Failure("invalid_fill_receipt"))?;
    let approved = plan["approved_fields"]
        .as_array()
        .ok_or(Failure("invalid_fill_receipt"))?;
    let mut seen = std::collections::HashSet::new();
    if plan["state"] != "consumed"
        || results
            .iter()
            .any(|r| !seen.insert(&r["field_id"]) || !approved.contains(&r["field_id"]))
    {
        return Err(Failure("invalid_fill_receipt"));
    }
    let completed = results
        .iter()
        .filter(|r| r["status"] == "filled")
        .map(|r| &r["field_id"])
        .collect::<std::collections::HashSet<_>>();
    Ok(match receipt["state"].as_str() {
        Some("form_filled")
            if approved.iter().any(|id| !completed.contains(id))
                || plan["inspection"]["fields"]
                    .as_array()
                    .ok_or(Failure("invalid_fill_receipt"))?
                    .iter()
                    .any(|f| f["required"] == true && !completed.contains(&f["field_id"]))
                || results.iter().any(|r| r["status"] != "filled") =>
        {
            "needs_input"
        }
        Some("form_filled") => "form_filled",
        Some("needs_input") => "needs_input",
        Some("manual_required") => "manual_required",
        Some("failed") => "failed",
        _ => return Err(Failure("invalid_fill_receipt")),
    })
}
