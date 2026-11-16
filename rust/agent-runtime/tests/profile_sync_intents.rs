//! Final-gate cases: an uncertain or corrupt save cannot be cleared by absent portal fields.
use automated_apply_agents::{Failure, execution::profile_sync_work as sync};
use chrono::{DateTime, Utc};
use serde_json::json;
use uuid::Uuid;
#[test]
fn profile_save_intent_requires_typed_reference_document_and_past_admission() {
    let now = DateTime::parse_from_rfc3339("2026-11-16T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let valid = json!({"id":Uuid::new_v4(),"document_id":"fictional-profile-document-one","new_reference":"a".repeat(64),"previous_reference":null,"at":"2026-11-15T00:00:00Z","outcome":"UNKNOWN"});
    sync::validate_attempt(&valid, now).unwrap();
    for (key, value) in [
        ("id", json!("missing")),
        ("document_id", json!("short")),
        ("new_reference", json!(null)),
        ("previous_reference", json!("lost")),
        ("at", json!("2026-11-17T00:00:00Z")),
        ("outcome", json!("reset")),
        ("field", json!("email")),
    ] {
        let mut corrupt = valid.clone();
        corrupt[key] = value;
        assert_eq!(
            sync::validate_attempt(&corrupt, now),
            Err(Failure("profile_sync_attempt_requires_review"))
        );
    }
}
#[test]
fn profile_transport_exposes_current_approved_fields_without_local_contacts_or_old_intents() {
    let work = json!({"operation":"sync_profile","sync_field":"skills","sync_phase":"prepare","skills_before":["Existing Skill"],"skills_additions":["Rust"],"account_sha256":"a".repeat(64),"phone":"PRIVATE_PHONE_CANARY","candidate_email":"PRIVATE_CONTACT_CANARY","sync_attempt":{"secret":"PRIVATE_OLD_INTENT_CANARY"},"ciphertext":"PRIVATE_RESUME_CANARY"});
    let transport = sync::descriptor(&work);
    assert_eq!(transport["skills_additions"], json!(["Rust"]));
    assert_eq!(transport["sync_phase"], "prepare");
    assert!(transport["permit_expires_at"].is_null());
    assert!(!transport.to_string().contains("PRIVATE_"));
}
