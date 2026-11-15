use automated_apply_agents::mailboxes::{Settings, Slot, browser_nonce, consent, routes};
use std::collections::BTreeMap;
#[test]
fn account_configuration_and_strict_consent_never_grant_sending() {
    assert!(Settings::from_values(&BTreeMap::new(), false).is_ok());
    for (key, value) in [
        (
            "GMAIL_LOCAL_ALLOWED_EMAILS",
            "[\"Display <fixture@example.com>\"]",
        ),
        ("GMAIL_LOCAL_ALLOWED_EMAILS", "{}"),
        ("GMAIL_LOCAL_ALLOWED_EMAILS", "[\"no-at-sign\"]"),
        ("GMAIL_LOCAL_ALLOWED_EMAILS", "[\"@example.com\"]"),
        ("OAUTH_STATE_TTL_SECONDS", "59"),
        ("OAUTH_STATE_TTL_SECONDS", "901"),
        ("GMAIL_LOCAL_ACCOUNTS_ENABLED", "perhaps"),
    ] {
        assert!(
            Settings::from_values(&BTreeMap::from([(key.into(), value.into())]), false).is_err()
        );
    }
    for raw in [
        r#"{"account_consent":1,"read_and_draft_consent":true}"#,
        r#"{"account_consent":true,"read_and_draft_consent":"yes"}"#,
        r#"{"account_consent":true,"read_and_draft_consent":true,"send":true}"#,
    ] {
        assert!(consent(raw.as_bytes()).is_err());
    }
    assert!(consent(br#"{"account_consent":true,"read_and_draft_consent":true}"#).is_ok());
    for slot in ["0", "3", "01", "1/verify", "1%2fverify"] {
        assert!(Slot::parse(slot).is_err());
    }
}
#[test]
fn browser_states_and_cookies_are_bounded_unique_and_unambiguous() {
    let a = browser_nonce();
    let b = browser_nonce();
    assert_ne!(a, b);
    assert_eq!(a.len(), 64);
    let state = format!("mailbox.1.{a}");
    let query = format!("state={state}&code=fictional-code&scope=openid&authuser=0&prompt=consent");
    let decoded = routes::callback(Some(&query)).unwrap();
    assert_eq!(decoded.state, state);
    assert_eq!(decoded.code.as_deref(), Some("fictional-code"));
    for query in [
        format!("state={state}&state={state}"),
        format!("state={state}&code=a&code=b"),
        format!("state={state}&code={}", "x".repeat(4097)),
        format!("state={state}&unknown=1"),
        format!("state=mailbox.3.{a}"),
        format!("state=legacy.{a}"),
        format!("state={state}&code=%0Aprivate"),
    ] {
        assert!(routes::callback(Some(&query)).is_err());
    }
    let mut headers = axum::http::HeaderMap::new();
    headers.insert(
        "cookie",
        format!("unrelated=1; gmail54_oauth_1={b}; another=2")
            .parse()
            .unwrap(),
    );
    assert_eq!(routes::browser_cookie(&headers, Slot::One).unwrap(), b);
    assert!(routes::browser_cookie(&headers, Slot::Two).is_err());
    headers.append("cookie", format!("gmail54_oauth_1={a}").parse().unwrap());
    assert!(routes::browser_cookie(&headers, Slot::One).is_err());
}
#[test]
fn account_routes_are_closed_and_do_not_include_send_or_arbitrary_grants() {
    for path in [
        routes::ACCOUNTS,
        routes::CALLBACK,
        "/api/v1/integrations/gmail/local/accounts/1/connect",
        "/api/v1/integrations/gmail/local/accounts/2/disconnect",
    ] {
        assert!(routes::route(path).is_some());
    }
    for action in [
        "send",
        "delete",
        "refresh",
        "connect/extra",
        "../connect",
        "authorize-submission",
    ] {
        assert!(routes::route(&format!("{}/1/{action}", routes::ACCOUNTS)).is_none());
    }
}
