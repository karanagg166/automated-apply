//! Deferred saved-company public projection privacy and timestamp safeguards.
use automated_apply_agents::companies;
use serde_json::{Value, json};
fn now() -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::parse_from_rfc3339("2026-11-17T12:00:00Z")
        .unwrap()
        .to_utc()
}
#[test]
fn company_people_projection_excludes_vendor_mailbox_phone_and_intent_fields_and_qualifies_future_claims()
 {
    let value = json!({"name":"Fictional Professional","role":"CTO","linkedin_url":"https://linkedin.com/in/fictional-professional?ref=fixture","evidence_url":"https://company-fixture.example/team","source":"public_search","observed_at":"2026-11-17T16:30:00+05:30","verification_status":"human_confirmed","email":"PRIVATE_MAILBOX_CANARY","phone":"PRIVATE_PHONE_CANARY","token":"PRIVATE_TOKEN_CANARY","evidence":{"text":"Fictional saved professional finding","raw_vendor":"PRIVATE_RAW_VENDOR_CANARY"}});
    let result = companies::person(value.clone(), now()).unwrap();
    for canary in [
        "PRIVATE_MAILBOX_CANARY",
        "PRIVATE_PHONE_CANARY",
        "PRIVATE_TOKEN_CANARY",
        "PRIVATE_RAW_VENDOR_CANARY",
    ] {
        assert!(!result.to_string().contains(canary));
    }
    assert_eq!(result["observed_at"], "2026-11-17T11:00:00+00:00");
    assert_eq!(result["live_verified"], false);
    assert_eq!(result["email_send_ready"], false);
    assert_eq!(result["outreach_mode"], "manual");
    let mut future = value;
    future["observed_at"] = json!("2026-11-18T00:00:00Z");
    let result = companies::person(future, now()).unwrap();
    assert_eq!(result["stale"], true);
    assert_eq!(result["verification_status"], "requires_review");
    assert_eq!(result["recorded_verification_status"], "human_confirmed");
}
#[test]
fn company_observation_projection_keeps_declared_evidence_and_refuses_private_links_or_malformed_attributes()
 {
    let base = json!({"id":"11111111-1111-4111-8111-111111111111","source":"manual","source_url":"https://company-fixture.example/company","observed_at":"2026-11-16T12:00:00Z","verification_status":"source_reported","attributes":{"employee_count":12,"team_size_band":"11-50","technology_stack":["Rust"],"private_billing_key":"PRIVATE_COMPANY_KEY_CANARY","raw_payload":{"private":"PRIVATE_COMPANY_RAW_CANARY"}}});
    let result = companies::observation(base.clone(), now()).unwrap();
    assert_eq!(result["attributes"]["employee_count"], 12);
    assert!(!result.to_string().contains("PRIVATE_COMPANY_KEY_CANARY"));
    assert!(!result.to_string().contains("PRIVATE_COMPANY_RAW_CANARY"));
    for url in [
        "http://company-fixture.example/",
        "https://127.0.0.1/private",
        "https://user:password@company-fixture.example/",
        "javascript:alert(1)",
    ] {
        let mut v = base.clone();
        v["source_url"] = json!(url);
        assert!(companies::observation(v, now()).is_err());
    }
    for v in [
        json!({"employee_count":0}),
        json!({"employee_count":1.5}),
        json!({"technology_stack":[5]}),
        json!({"description":"x".repeat(4001)}),
        json!({"historical":"yes"}),
        Value::Null,
    ] {
        let mut value = base.clone();
        value["attributes"] = v;
        assert!(companies::observation(value, now()).is_err());
    }
}
