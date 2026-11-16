//! Pure retained-evidence predicates. Reads do not reverify a provider or mint a receipt.
//! Malformed receipt existence still fences replay elsewhere, regardless of these predicates.
use chrono::{DateTime, Utc};
use serde_json::Value;
use uuid::Uuid;

fn sha(value: &Value) -> bool {
    value.as_str().is_some_and(|s| {
        s.len() == 64
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}
fn requisition<'a>(key: &'a str, prefix: &str) -> Option<&'a str> {
    key.strip_prefix(prefix)
        .filter(|s| (10..=20).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_digit()))
}
fn date(value: &Value) -> Option<DateTime<Utc>> {
    value
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|d| d.with_timezone(&Utc))
}
pub fn recorded_application(key: &str, value: &Value, now: DateTime<Utc>) -> bool {
    let Some(req) = requisition(key, "naukri_receipt:") else {
        return false;
    };
    value.is_object()
        && value["requisition"] == req
        && value["confirmation_source"] == "naukri_application_status_ui"
        && value["operation_mode"] == "owner_authorized_software_operated_ui"
        && value["status"] == "Application Sent"
        && value["persistent_after_reload"] == true
        && sha(&value["private_evidence_sha256"])
        && date(&value["observed_at"]).is_some_and(|d| d <= now + chrono::Duration::minutes(5))
}
pub fn worker_recorded(key: &str, value: &Value, now: DateTime<Utc>) -> bool {
    let Some(req) = requisition(key, "naukri_worker_receipt:") else {
        return false;
    };
    if !value.is_object()
        || value["requisition"] != req
        || value["confirmation_source"] != "naukri_application_status_ui"
        || value["operation_mode"] != "recurring_worker_ui"
        || value["persistent_after_reload"] != true
        || value["status"] != "Application Sent"
        || !sha(&value["account_sha256"])
    {
        return false;
    }
    let first = &value["first_observation"];
    let second = &value["second_observation"];
    if first.get("document_id").is_none()
        || second.get("document_id").is_none()
        || first["document_id"] == second["document_id"]
        || !sha(&first["evidence_sha256"])
        || !sha(&second["evidence_sha256"])
        || second["state"] != "APPLICATION_SENT"
        || second["account_sha256"] != value["account_sha256"]
    {
        return false;
    }
    date(&first["observed_at"])
        .zip(date(&value["observed_at"]))
        .is_some_and(|(first, last)| first < last && last <= now + chrono::Duration::minutes(5))
}
/// Full first-worker-receipt binding, after the caller has verified the current account.
/// A historical/reconciled observation without an admitted Apply is insufficient.
pub fn first_worker_bound(
    key: &str,
    receipt: &Value,
    work: &Value,
    account: &Value,
    now: DateTime<Utc>,
) -> bool {
    worker_recorded(key, receipt, now)
        && receipt["worker_dispatched"] == true
        && account["approved"] == true
        && ["candidate_profile_id", "profile_binding_id"]
            .iter()
            .all(|key| {
                account[key]
                    .as_str()
                    .and_then(|s| s.parse::<Uuid>().ok())
                    .is_some()
            })
        && account["revision"].as_i64().is_some_and(|n| n >= 1)
        && receipt["queue_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .is_some()
        && work["id"] == receipt["queue_id"]
        && work["platform"] == "naukri"
        && work["requisition"] == receipt["requisition"]
        && work["candidate_profile_id"] == account["candidate_profile_id"]
        && receipt["account_sha256"] == account["account_sha256"]
        && work["account_sha256"] == account["account_sha256"]
        && work["account_binding_revision"] == account["revision"]
        && work["stage"] == "SUBMITTED_CONFIRMED"
        && work["submission_mode"] == "recurring_worker_ui"
        && work["admitted_actions"].as_array().is_some_and(|actions| {
            actions.iter().any(|a| {
                a["fingerprint"]
                    .as_str()
                    .is_some_and(|s| s.starts_with("apply:"))
            })
        })
}
