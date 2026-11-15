use automated_apply_agents::gmail_read::ReadClient;
use axum::{Router, body::Body, extract::Request, response::Response};
use serde_json::json;
use std::sync::{Arc, Mutex};
async fn fixture(
    status: u16,
    body: String,
) -> (
    String,
    Arc<Mutex<Vec<(String, String, bool)>>>,
    tokio::task::JoinHandle<()>,
) {
    let calls = Arc::new(Mutex::new(vec![]));
    let capture = calls.clone();
    let app = Router::new().fallback(move |request: Request| {
        let capture = capture.clone();
        let body = body.clone();
        async move {
            capture.lock().unwrap().push((
                request.method().to_string(),
                request.uri().to_string(),
                request
                    .headers()
                    .get("authorization")
                    .is_some_and(|v| v == "Bearer fictional-token"),
            ));
            Response::builder()
                .status(status)
                .header("Location", "https://denied.example/must-not-follow")
                .body(Body::from(body))
                .unwrap()
        }
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (format!("http://{address}/"), calls, task)
}
#[tokio::test(flavor = "current_thread")]
async fn gmail_transport_is_get_only_bounds_pages_and_encodes_queries_without_path_injection() {
    let (url, calls, server) = fixture(200, json!({"messages":[]}).to_string()).await;
    let client = ReadClient::new("fictional-token", true, Some(&url)).unwrap();
    client
        .messages(
            &["Label_fixture".into()],
            Some("from:fictional@example.invalid & path=/send"),
            Some("opaque+/="),
            999,
        )
        .await
        .unwrap();
    client.message("fixture_id-1", false).await.unwrap();
    client.message("fixture_id-1", true).await.unwrap();
    let calls = calls.lock().unwrap();
    assert_eq!(calls.len(), 3);
    assert!(calls.iter().all(|c| c.0 == "GET" && c.2));
    assert!(calls[0].1.starts_with("/messages?maxResults=25&"));
    assert!(calls[0].1.contains("%26+path%3D%2Fsend"));
    assert!(calls[1].1.contains("format=metadata"));
    assert!(calls[2].1.contains("format=full"));
    assert!(
        calls[1]
            .1
            .contains("metadataHeaders=Authentication-Results")
    );
    server.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn gmail_transport_preserves_fixed_error_classes_limits_and_refuses_redirects() {
    for (status, body, code) in [
        (401, "{}".into(), "gmail_read_permission_required"),
        (403, "{}".into(), "gmail_read_permission_required"),
        (429, "{}".into(), "gmail_read_rate_limited"),
        (302, "{}".into(), "gmail_read_upstream_error"),
        (200, "[]".into(), "gmail_read_invalid_response"),
        (
            200,
            "invalid".into(),
            "gmail_read_transport_or_response_error",
        ),
        (
            200,
            "x".repeat(1024 * 1024 + 1),
            "gmail_read_response_limit",
        ),
    ] {
        let (url, calls, server) = fixture(status, body).await;
        let client = ReadClient::new("fictional-token", true, Some(&url)).unwrap();
        assert_eq!(
            client.messages(&[], None, None, 1).await.unwrap_err().0,
            code
        );
        assert_eq!(calls.lock().unwrap().len(), 1);
        server.abort();
    }
}
#[tokio::test(flavor = "current_thread")]
async fn gmail_invalid_identifiers_and_write_names_never_reach_transport_or_override_production_host()
 {
    let (url, calls, server) = fixture(200, "{}".into()).await;
    let client = ReadClient::new("fictional-token", true, Some(&url)).unwrap();
    for id in [
        "../send",
        "id?alt=media",
        "",
        "send",
        "delete",
        "batchModify",
    ] {
        assert!(client.message(id, false).await.is_err());
    }
    assert!(calls.lock().unwrap().is_empty());
    assert!(ReadClient::new("fictional-token", false, Some(&url)).is_err());
    assert!(ReadClient::new("fictional-token", true, Some("http://localhost:12345/")).is_err());
    assert!(ReadClient::new("fictional-token", true, None).is_err());
    assert!(ReadClient::new("bad\r\ntoken", false, None).is_err());
    server.abort();
}
