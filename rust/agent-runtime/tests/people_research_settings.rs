//! Deferred money/retention boundaries. No actual key, provider request or balance assertion.
use automated_apply_agents::{
    people_research::settings::Settings,
    research_contract::{self, Kind},
};
use serde_json::{Value, json};
use std::collections::BTreeMap;
fn values() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("PEOPLE_SEARCH_ENABLED".into(), "true".into()),
        (
            "SERPER_API_KEY".into(),
            "PRIVATE_FICTIONAL_SEARCH_KEY_CANARY".into(),
        ),
        ("PUBLIC_SEARCH_RIGHTS_REVIEWED".into(), "true".into()),
        (
            "PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL".into(),
            "https://search-fixture.example/permission".into(),
        ),
        (
            "PUBLIC_SEARCH_ALLOWED_DOMAINS".into(),
            "{\"company-fixture.example\":\"https://company-fixture.example/permission\"}".into(),
        ),
    ])
}
fn query() -> Value {
    research_contract::normalize(Kind::PeopleQuery,json!({"company_name":"Fictional Company","company_domain":"company-fixture.example","research_mode":"official_company","allow_paid":true}),chrono::DateTime::parse_from_rfc3339("2026-11-15T12:00:00Z").unwrap().to_utc()).unwrap()
}
#[test]
fn paid_search_requires_each_independent_saved_right_credential_domain_and_owner_opt_in() {
    let settings = Settings::from_values(&values()).unwrap();
    assert!(settings.require(&query()).is_ok());
    for (field, value) in [
        ("PEOPLE_SEARCH_ENABLED", None),
        ("SERPER_API_KEY", None),
        ("PUBLIC_SEARCH_RIGHTS_REVIEWED", None),
        ("PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL", None),
        ("PUBLIC_SEARCH_ALLOWED_DOMAINS", Some("{}")),
        ("SERPER_MONTHLY_LIMIT", Some("0")),
    ] {
        let mut v = values();
        v.remove(field);
        if let Some(value) = value {
            v.insert(field.into(), value.into());
        }
        assert!(
            Settings::from_values(&v)
                .unwrap()
                .require(&query())
                .is_err(),
            "gate {field}"
        );
    }
    let mut q = query();
    q["allow_paid"] = json!(false);
    assert!(settings.require(&q).is_err());
    let mut q = query();
    q["research_mode"] = json!("public_profiles");
    assert!(settings.require(&q).is_err());
    let mut v = values();
    v.insert("LINKEDIN_SEARCH_RETENTION_AUTHORIZED".into(), "true".into());
    assert!(Settings::from_values(&v).unwrap().require(&q).is_ok());
    let mut q = query();
    q["company_domain"] = json!("other-fixture.example");
    assert!(settings.require(&q).is_err());
    let mut q = query();
    q["source"] = json!("linkedin");
    assert!(settings.require(&q).is_err());
    let mut q = query();
    q["manual_people"] = json!([{}]);
    assert!(settings.require(&q).is_err());
    let s = settings.status();
    assert_eq!(s["budget_unit"], "search_request");
    assert_eq!(s["provider_balance_verified"], false);
    assert_eq!(s["live_verified"], false);
    assert_eq!(s["dispatch_authorized"], false);
    assert!(
        !s.to_string()
            .contains("PRIVATE_FICTIONAL_SEARCH_KEY_CANARY")
    );
    assert!(!s.to_string().contains("company-fixture.example"));
}
#[test]
fn paid_search_private_settings_reject_nonfinite_limits_unsafe_rights_and_unbounded_keys() {
    for (field, value) in [
        ("SERPER_MONTHLY_LIMIT", "NaN"),
        ("SERPER_MONTHLY_LIMIT", "-1"),
        ("SERPER_MONTHLY_LIMIT", "10000000000"),
        (
            "PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL",
            "https://127.0.0.1/private",
        ),
        ("PUBLIC_SEARCH_ALLOWED_DOMAINS", "[]"),
        (
            "PUBLIC_SEARCH_ALLOWED_DOMAINS",
            "{\"https://company-fixture.example\":\"https://company-fixture.example/terms\"}",
        ),
        (
            "PUBLIC_SEARCH_ALLOWED_DOMAINS",
            "{\"company-fixture.example\":\"https://localhost/terms\"}",
        ),
        ("SERPER_API_KEY", "key with whitespace"),
        ("PEOPLE_SEARCH_ENABLED", "unknown"),
    ] {
        let mut v = values();
        v.insert(field.into(), value.into());
        assert!(Settings::from_values(&v).is_err(), "setting {field}");
    }
    let mut v = values();
    v.insert("SERPER_API_KEY".into(), "x".repeat(4097));
    assert!(Settings::from_values(&v).is_err());
    let defaults = Settings::from_values(&BTreeMap::new()).unwrap().status();
    assert_eq!(defaults["enabled"], false);
    assert_eq!(defaults["monthly_local_request_limit"], 100);
}
