//! Deferred private configuration/route selection guards. No tokens from disk or transport.
use automated_apply_agents::apify_jobs::settings::Settings;
use serde_json::{Value, json};
use std::collections::BTreeMap;
fn actor(name: &str) -> Value {
    json!({"actor_id":format!("fictional/{name}"),"build":"1.2.3","enabled":true,"reviewed":true,"review_expires_at":"2026-11-17T12:00:00Z","platform_usage_included":true,"account_spending_limit_verified":true,"schema_evidence_url":"https://actor-fixture.example/schema","pricing_evidence_url":"https://actor-fixture.example/pricing","permission_evidence_url":"https://actor-fixture.example/permission","pricing_model":"PAY_PER_EVENT","estimated_per_item_usd":0.001,"field_map":{"limit":"maxItems"}})
}
fn values() -> BTreeMap<String, String> {
    BTreeMap::from([("APIFY_API_TOKEN".into(),"PRIVATE_SETTINGS_TOKEN_CANARY".into()),("APIFY_MONTHLY_LIMIT_USD".into(),"1.000001".into()),("APIFY_PER_RUN_CAP_USD".into(),"0.100001".into()),("APIFY_SOURCES".into(),json!({"naukri":actor("fallback")}).to_string()),("APIFY_SOURCE_ROUTES".into(),json!({"naukri":[actor("first"),actor("second")]}).to_string()),("APIFY_BUILD_REVIEWS".into(),json!({"naukri:fictional/first":{"build_id":"firstBuild","schema_digest":"a".repeat(64)},"naukri:fictional/second":{"build_id":"secondBuild","schema_digest":"b".repeat(64)}}).to_string())])
}
#[test]
fn saved_route_selection_is_deterministic_and_credential_context_is_not_a_provider_rotation() {
    let now = chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc();
    let v = values();
    let settings = Settings::from_values(&v).unwrap();
    let plan = settings.plan("naukri", json!({}), true, now).unwrap();
    assert_eq!(
        plan.actor_metadata().unwrap().path(),
        "actors/fictional~first"
    );
    assert_eq!(plan.cap().decimal(), "0.100001");
    let second = settings.plan("naukri", json!({}), true, now).unwrap();
    assert_eq!(plan.context(), second.context());
    assert!(!plan.context().contains("CANARY"));
    assert!(settings.plan("naukri", json!({}), false, now).is_err());
    let mut v = v;
    v.remove("APIFY_BUILD_REVIEWS");
    assert!(
        Settings::from_values(&v)
            .unwrap()
            .plan("naukri", json!({}), true, now)
            .is_err()
    );
}
#[test]
fn malformed_route_review_or_nonexact_money_is_rejected_before_any_admission() {
    for (key, value) in [
        ("APIFY_MONTHLY_LIMIT_USD", "1e2"),
        ("APIFY_PER_RUN_CAP_USD", "0.0000001"),
        ("APIFY_PER_RUN_CAP_USD", "100.000001"),
        (
            "APIFY_BUILD_REVIEWS",
            r#"{"naukri":{"build_id":"../other","schema_digest":"invalid"}}"#,
        ),
        ("APIFY_SOURCE_ROUTES", r#"{"naukri":[{},{},{},{},{},{}]}"#),
    ] {
        let mut v = values();
        v.insert(key.into(), value.into());
        assert!(Settings::from_values(&v).is_err(), "{key}");
    }
}
