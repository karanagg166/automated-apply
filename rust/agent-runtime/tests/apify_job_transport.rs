//! Deferred transport configuration guards; no HTTP.
use automated_apply_agents::apify_jobs::transport::Client;
use std::collections::BTreeMap;
#[test]
fn paid_transport_substitution_requires_explicit_testing_numeric_loopback_and_sensitive_token_syntax()
 {
    for origin in [
        "http://localhost:12345/v2/",
        "http://127.0.0.1:80/v2/",
        "https://127.0.0.1:12345/v2/",
        "http://127.0.0.1:12345/",
        "http://127.0.0.1:12345/v2/?token=forbidden",
        "http://user:secret@127.0.0.1:12345/v2/",
    ] {
        let values =
            BTreeMap::from([("RUST_APIFY_EXECUTION_FIXTURE_ORIGIN".into(), origin.into())]);
        assert!(Client::from_values(&values, true).is_err());
    }
    let values = BTreeMap::from([(
        "RUST_APIFY_EXECUTION_FIXTURE_ORIGIN".into(),
        "http://127.0.0.1:12345/v2/".into(),
    )]);
    assert!(Client::from_values(&values, false).is_err());
    assert!(Client::from_values(&values, true).is_ok());
    for token in ["space token", "newline\ntoken"] {
        assert!(
            Client::from_values(
                &BTreeMap::from([("APIFY_API_TOKEN".into(), token.into())]),
                true
            )
            .is_err()
        );
    }
}
