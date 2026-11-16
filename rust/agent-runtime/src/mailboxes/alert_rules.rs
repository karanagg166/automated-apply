//! Only Gmail's unambiguous receiving-domain authentication permits selected alert body use.
use super::*;
use regex::Regex;
use std::sync::LazyLock;
pub const SENDER: &str = "naukrialerts@naukri.com";
pub fn policy(mut value: Value) -> Result<Value> {
    static SCHEMA: LazyLock<Value> = LazyLock::new(|| {
        serde_json::from_str(include_str!("../../schemas/gmail-alert-policy.json"))
            .expect("frozen alert policy")
    });
    static VALIDATOR: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
        jsonschema::draft202012::options()
            .build(&SCHEMA)
            .expect("alert policy schema")
    });
    let invalid = || Failure("invalid_gmail_alert_policy");
    let object = value.as_object_mut().ok_or_else(invalid)?;
    if !object.contains_key("interval_seconds") {
        object.insert("interval_seconds".into(), json!(900));
    }
    for field in [
        "expected_version",
        "expected_generation",
        "interval_seconds",
    ] {
        if let Some(value) = object.get_mut(field) {
            *value = crate::profile_contract::number(&SCHEMA["properties"][field], value.clone())
                .map_err(|_| invalid())?;
        }
    }
    if !VALIDATOR.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
pub fn authenticated(message: &Value) -> bool {
    let Some(headers) = message["payload"]["headers"]
        .as_array()
        .filter(|a| a.len() <= 100)
    else {
        return false;
    };
    let mut from = Vec::new();
    let mut auth = Vec::new();
    for header in headers {
        let (Some(name), Some(value)) = (header["name"].as_str(), header["value"].as_str()) else {
            return false;
        };
        match automated_apply_domain::text::folded(name).as_str() {
            "from" => from.push(value),
            "authentication-results" => auth.push(value),
            _ => {}
        }
    }
    if from.len() != 1
        || auth.len() != 1
        || crate::mail_evidence::single_address(from[0]).as_deref() != Some(SENDER)
    {
        return false;
    }
    let result = automated_apply_domain::text::folded(
        &auth[0]
            .split(crate::context_contract::python_space)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" "),
    );
    static DMARC: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?:^|[;\s])dmarc=pass\b[^;]*\bheader\.from=naukri\.com(?:[;\s]|$)").unwrap()
    });
    static DKIM: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?:^|[;\s])dkim=pass\b[^;]*\bheader\.(?:i=@|d=)naukri\.com(?:[;\s]|$)")
            .unwrap()
    });
    result.starts_with("mx.google.com;") && DMARC.is_match(&result) && DKIM.is_match(&result)
}
pub fn topic(message: &Value) -> bool {
    static TOPIC: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)\b(?:jobs?|hiring|vacanc\w*|recommend\w*|opportunit\w*)\b").unwrap()
    });
    crate::mail_evidence::headers(message)
        .get("subject")
        .is_some_and(|s| TOPIC.is_match(s))
}
pub fn query(value: &Value) -> Result<String> {
    let after = value["scan_after"]
        .as_i64()
        .ok_or(Failure("invalid_gmail_alert_saved_record"))?;
    let until = value["scan_until"]
        .as_i64()
        .filter(|n| *n > after)
        .ok_or(Failure("invalid_gmail_alert_saved_record"))?;
    Ok(format!(
        "in:inbox from:{SENDER} after:{after} before:{until}"
    ))
}
pub fn links(links: &Value) -> Result<Vec<(String, String)>> {
    let mut indices = std::collections::HashMap::new();
    let mut result = Vec::new();
    for raw in links
        .as_array()
        .ok_or(Failure("invalid_gmail_alert_saved_record"))?
        .iter()
        .take(25)
    {
        let Some(url) = raw
            .as_str()
            .and_then(|s| crate::execution::filters::naukri_url(s).ok())
        else {
            continue;
        };
        let requisition = url
            .rsplit('-')
            .next()
            .ok_or(Failure("invalid_gmail_alert_saved_record"))?
            .to_owned();
        if let Some(index) = indices.get(&requisition) {
            result[*index] = (requisition, url);
        } else {
            indices.insert(requisition.clone(), result.len());
            result.push((requisition, url));
        }
    }
    Ok(result)
}
