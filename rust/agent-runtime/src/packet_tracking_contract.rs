//! Owner reports are explicit attestations, never employer or worker receipts.
use crate::{Failure, Result};
use serde::Serialize;
use serde_json::{Map, Value};

pub const CONFIRMATION: &str = "I submitted this application on the official website";
pub const TRACKING: &[&str] = &[
    "not_applied",
    "applied_manually",
    "applied_verified",
    "application_incomplete",
    "application_rejected",
    "interview_scheduled",
    "offer_received",
    "archived",
];
#[derive(Serialize)]
pub struct Submission {
    pub expected_revision: i32,
    pub idempotency_key: String,
    pub human_confirmed: bool,
    pub confirmation: String,
    pub receipt_reference: Option<String>,
    pub note: Option<String>,
}
#[derive(Serialize)]
pub struct Tracking {
    pub expected_revision: i32,
    pub tracking_state: Option<String>,
    pub lifecycle_state: Option<String>,
    pub note: Option<String>,
}
fn invalid() -> Failure {
    Failure("invalid_packet_tracking_request")
}
fn object(input: &Value, allowed: &[&str]) -> Result<Map<String, Value>> {
    let body = input.as_object().ok_or_else(invalid)?;
    if body.keys().any(|k| !allowed.contains(&k.as_str())) {
        return Err(invalid());
    }
    Ok(body.clone())
}
fn revision(body: &Map<String, Value>) -> Result<i32> {
    crate::profile_contract::pagination_integer(
        body.get("expected_revision").cloned().ok_or_else(invalid)?,
        1,
        2147483646,
    )
    .map(|v| v as i32)
    .map_err(|_| invalid())
}
fn optional(body: &Map<String, Value>, key: &str, max: usize) -> Result<Option<String>> {
    body.get(key)
        .filter(|v| !v.is_null())
        .map(|v| {
            let s = v.as_str().ok_or_else(invalid)?.trim();
            if !(1..=max).contains(&s.chars().count()) {
                return Err(invalid());
            }
            Ok(s.into())
        })
        .transpose()
}
pub fn submission(input: Value) -> Result<Submission> {
    let body = object(
        &input,
        &[
            "expected_revision",
            "idempotency_key",
            "human_confirmed",
            "confirmation",
            "receipt_reference",
            "note",
        ],
    )?;
    let key = optional(&body, "idempotency_key", 100)?
        .filter(|s| {
            s.len() >= 8
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
        })
        .ok_or_else(invalid)?;
    if body.get("human_confirmed") != Some(&Value::Bool(true))
        || body.get("confirmation").and_then(Value::as_str) != Some(CONFIRMATION)
    {
        return Err(invalid());
    }
    Ok(Submission {
        expected_revision: revision(&body)?,
        idempotency_key: key,
        human_confirmed: true,
        confirmation: CONFIRMATION.into(),
        receipt_reference: optional(&body, "receipt_reference", 255)?,
        note: optional(&body, "note", 1000)?,
    })
}
pub fn tracking(input: Value) -> Result<Tracking> {
    let body = object(
        &input,
        &[
            "expected_revision",
            "tracking_state",
            "lifecycle_state",
            "note",
        ],
    )?;
    // Literal values are exact: string trimming applies only to free text.
    let literal = |key, allowed: &[&str]| -> Result<Option<String>> {
        body.get(key)
            .filter(|v| !v.is_null())
            .map(|v| {
                let s = v
                    .as_str()
                    .filter(|s| allowed.contains(s))
                    .ok_or_else(invalid)?;
                Ok(s.into())
            })
            .transpose()
    };
    let tracking_state = literal("tracking_state", TRACKING)?;
    let lifecycle_state = literal(
        "lifecycle_state",
        &["external_application_opened", "withdrawn", "abandoned"],
    )?;
    if tracking_state.is_none() && lifecycle_state.is_none() {
        return Err(invalid());
    }
    Ok(Tracking {
        expected_revision: revision(&body)?,
        tracking_state,
        lifecycle_state,
        note: optional(&body, "note", 1000)?,
    })
}
