//! Missing-fact requests retain no credential or protected-declaration answers.
//! Contract validation and identity binding confer no owner approval.
use crate::{
    Failure, Result,
    answer_contract::{self, Generate},
    context_contract::{integer, python_space},
    legacy_regex::Regex,
};
use automated_apply_domain::text::folded;
use serde::Serialize;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::sync::LazyLock;
use uuid::Uuid;

#[derive(Serialize)]
pub struct Create {
    #[serde(flatten)]
    pub request: Generate,
    pub packet_id: Option<Uuid>,
    pub missing_fact: String,
    pub reason: String,
    pub required_input_type: String,
}
#[derive(Serialize)]
pub struct Edit {
    pub expected_version: u64,
    pub answer: String,
    pub evidence_note: String,
}
#[derive(Serialize)]
pub struct Approve {
    pub expected_version: u64,
    pub expected_profile_version: u64,
    pub factual_confirmation: bool,
}
fn invalid() -> Failure {
    Failure("invalid_missing_input_request")
}
fn string(value: &Value, minimum: usize, maximum: usize) -> Result<String> {
    let value = value.as_str().ok_or_else(invalid)?.trim();
    if !(minimum..=maximum).contains(&value.chars().count()) {
        return Err(invalid());
    }
    Ok(value.into())
}
fn version(input: Option<&Value>) -> Result<u64> {
    let value = integer(input.ok_or_else(invalid)?.clone())
        .map_err(|_| invalid())?
        .as_u64()
        .ok_or_else(invalid)?;
    if value == 0 {
        return Err(invalid());
    }
    Ok(value)
}
fn object(input: Value, allowed: &[&str]) -> Result<Map<String, Value>> {
    let input = input.as_object().ok_or_else(invalid)?.clone();
    if input.keys().any(|k| !allowed.contains(&k.as_str())) {
        return Err(invalid());
    }
    Ok(input)
}
pub fn normalize_create(input: Value) -> Result<Create> {
    let mut body = input.as_object().ok_or_else(invalid)?.clone();
    let packet_id = body
        .remove("packet_id")
        .filter(|v| !v.is_null())
        .map(|v| {
            v.as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)
        })
        .transpose()?;
    let missing_fact = string(&body.remove("missing_fact").ok_or_else(invalid)?, 1, 2000)?;
    let reason = string(
        &body
            .remove("reason")
            .unwrap_or(json!("No approved evidence supports an answer")),
        1,
        2000,
    )?;
    let input_type = body
        .remove("required_input_type")
        .unwrap_or(json!("evidence"));
    let input_type = input_type.as_str().ok_or_else(invalid)?;
    if !["text", "number", "choice", "evidence", "profile_edit"].contains(&input_type) {
        return Err(invalid());
    }
    Ok(Create {
        request: answer_contract::normalize(Value::Object(body)).map_err(|_| invalid())?,
        packet_id,
        missing_fact,
        reason,
        required_input_type: input_type.into(),
    })
}
pub fn normalize_edit(input: Value) -> Result<Edit> {
    let body = object(input, &["expected_version", "answer", "evidence_note"])?;
    Ok(Edit {
        expected_version: version(body.get("expected_version"))?,
        answer: string(body.get("answer").ok_or_else(invalid)?, 1, 10000)?,
        evidence_note: string(body.get("evidence_note").unwrap_or(&json!("")), 0, 2000)?,
    })
}
pub fn normalize_approve(input: Value) -> Result<Approve> {
    let body = object(
        input,
        &[
            "expected_version",
            "expected_profile_version",
            "factual_confirmation",
        ],
    )?;
    if body.get("factual_confirmation") != Some(&Value::Bool(true)) {
        return Err(invalid());
    }
    Ok(Approve {
        expected_version: version(body.get("expected_version"))?,
        expected_profile_version: version(body.get("expected_profile_version"))?,
        factual_confirmation: true,
    })
}
pub fn permitted(question: &str, answer_and_note: &str) -> Result<()> {
    if question.chars().count() > 2000 || answer_and_note.chars().count() > 12001 {
        return Err(Failure("missing_input_limit"));
    }
    static SENSITIVE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"password|passcode|verification code|one.time (?:code|password)|social security|government (?:id|identifier)|aadhaar|aadhar|pan (?:card|number)|passport|bank account|credit card|\bcvv\b|\botp\b|sexual orientation|gender identity|ethnicity|disabilit|veteran|religio|consent|legal declaration|terms and conditions",
            true,
        )
    });
    static CREDENTIAL: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"-----BEGIN .*PRIVATE KEY-----|\b(?:password|verification code|one.time code|otp|api[_ -]?key|access[_ -]?token)\s*(?:[:=]|is\b)",
            true,
        )
    });
    if SENSITIVE.is_match(question)? || CREDENTIAL.is_match(answer_and_note)? {
        return Err(Failure("sensitive_answer_not_retained"));
    }
    Ok(())
}
/// The legacy storage key is retained, but must never be used alone as an approval binding.
pub fn key_for(profile: Uuid, request: &Generate, packet: Option<Uuid>) -> String {
    let job = request
        .job_id
        .map(|id| id.to_string())
        .unwrap_or("None".into());
    let packet = packet.map(|id| id.to_string()).unwrap_or("None".into());
    let company = request.company_name.as_deref().unwrap_or("None");
    let description = request.job_description.as_deref().unwrap_or("None");
    let question = folded(request.question.trim_matches(python_space));
    let identity = format!("{profile}|{job}|{packet}|{company}|{description}|{question}");
    let hash = format!("{:x}", Sha256::digest(identity.as_bytes()));
    format!("needs_input:{}", &hash[..32])
}
/// Compare the complete identity before consulting an exact-context approval or its stamp.
pub fn matches_context(
    saved: &Value,
    profile: Uuid,
    request: &Generate,
    packet: Option<Uuid>,
) -> bool {
    saved["candidate_profile_id"] == json!(profile)
        && saved.get("job_id") == Some(&json!(request.job_id))
        && saved.get("packet_id") == Some(&json!(packet))
        && saved.get("company_name") == Some(&json!(request.company_name))
        && saved.get("job_description") == Some(&json!(request.job_description))
        && saved["question"].as_str().is_some_and(|s| {
            folded(s.trim_matches(python_space))
                == folded(request.question.trim_matches(python_space))
        })
}
