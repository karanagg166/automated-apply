//! Deferred callback namespace/cookie parser. No real authorization or mail request.
use automated_apply_agents::gmail_accounts::{self, oauth};
#[test]
fn legacy_read_callback_keeps_namespace_bounded_state_exact_cookie_and_duplicate_refusal() {
    let state = format!("read.{}", "a".repeat(64));
    let parsed =
        oauth::callback(Some(&format!("state={state}&code=fictional&scope=openid"))).unwrap();
    assert_eq!(parsed.state, state);
    assert_eq!(parsed.code.as_deref(), Some("fictional"));
    for raw in [
        format!("state={state}&state={state}&code=x"),
        format!("state={state}&code=x&code=y"),
        format!("state={state}&unexpected=x"),
        "state=read.short&code=x".into(),
        format!("state=mailbox.1.{}&code=x", "a".repeat(64)),
        format!("state=read.{}&code=x", "a".repeat(129)),
        format!("state={state}&code=%0A"),
    ] {
        assert!(oauth::callback(Some(&raw)).is_err());
    }
    let mut headers = axum::http::HeaderMap::new();
    headers.insert(
        "cookie",
        format!("other=value; gmail_oauth_browser={}", "b".repeat(64))
            .parse()
            .unwrap(),
    );
    assert_eq!(oauth::browser_cookie(&headers).unwrap(), "b".repeat(64));
    headers.append(
        "cookie",
        format!("gmail_oauth_browser={}", "b".repeat(64))
            .parse()
            .unwrap(),
    );
    assert!(oauth::browser_cookie(&headers).is_err());
    let mut local = axum::http::HeaderMap::new();
    local.insert(
        "cookie",
        format!("gmail54_oauth_1={}", "b".repeat(64))
            .parse()
            .unwrap(),
    );
    assert!(oauth::browser_cookie(&local).is_err());
    let id = uuid::Uuid::from_u128(1);
    for tail in [
        "connect/start",
        &format!("{id}/verify"),
        &format!("{id}/disconnect"),
    ] {
        assert!(gmail_accounts::io_route(&format!("{}/{tail}", gmail_accounts::PATH)).is_some());
    }
    for tail in [
        "connect/send",
        &format!("{id}/send"),
        &format!("{id}/verify/extra"),
    ] {
        assert!(gmail_accounts::io_route(&format!("{}/{tail}", gmail_accounts::PATH)).is_none());
    }
}
