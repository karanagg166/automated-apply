//! Read-only official model metadata, without candidate data, generation or database access.
use crate::{Failure, Result, configuration::private_values};
use serde::Serialize;
use serde_json::Value;
use std::{collections::BTreeMap, path::Path, time::Duration};

#[derive(Serialize)]
pub struct Status {
    provider: &'static str,
    model: String,
    key_authenticated: bool,
    model_available: bool,
    model_deprecated: Option<bool>,
    generation_flags_enabled: bool,
    candidate_data_authorized: bool,
    generation_performed: bool,
}
struct Settings {
    key: String,
    model: String,
    generation_flags_enabled: bool,
    candidate_data_authorized: bool,
}
fn enabled(values: &BTreeMap<String, String>, key: &str) -> bool {
    values
        .get(key)
        .is_some_and(|s| matches!(s.to_ascii_lowercase().as_str(), "true" | "1" | "yes" | "on"))
}
impl Settings {
    fn parse(values: &BTreeMap<String, String>) -> Result<Self> {
        let key = values
            .get("COHERE_API_KEY")
            .filter(|s| !s.trim().is_empty() && !s.chars().any(char::is_control))
            .ok_or(Failure("llm_not_configured"))?
            .clone();
        let model = values
            .get("COHERE_MODEL")
            .cloned()
            .unwrap_or("command-a-plus-05-2026".into());
        if !["command-a-plus-05-2026", "command-a-03-2025"].contains(&model.as_str()) {
            return Err(Failure("model_unavailable"));
        }
        let candidate_data_authorized = enabled(values, "COHERE_CANDIDATE_DATA_AUTHORIZED");
        let generation_flags_enabled = enabled(values, "COHERE_ENABLED")
            && enabled(values, "COHERE_EVALUATION_KEY_CONFIRMED")
            && enabled(values, "COHERE_OWNER_TEXT_AUTHORIZED")
            && candidate_data_authorized;
        Ok(Self {
            key,
            model,
            generation_flags_enabled,
            candidate_data_authorized,
        })
    }
}
async fn metadata(settings: Settings, endpoint: &str) -> Result<Status> {
    let client = reqwest::Client::builder()
        .no_proxy()
        .retry(reqwest::retry::never())
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(18))
        .build()
        .map_err(|_| Failure("provider_transport_configuration"))?;
    let mut response = client
        .get(endpoint)
        .bearer_auth(&settings.key)
        .header("X-Client-Name", "automated-apply-readonly-diagnostics")
        .send()
        .await
        .map_err(|_| Failure("cohere_transport_error"))?;
    match response.status().as_u16() {
        200 => {}
        401 | 403 | 498 => return Err(Failure("provider_authentication")),
        404 => return Err(Failure("model_unavailable")),
        429 => return Err(Failure("rate_limited")),
        _ => return Err(Failure("provider_error")),
    }
    let mut body = Vec::new();
    if response.content_length().is_some_and(|n| n > 65536) {
        return Err(Failure("provider_response_size"));
    }
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| Failure("cohere_transport_error"))?
    {
        if body.len() + chunk.len() > 65536 {
            return Err(Failure("provider_response_size"));
        }
        body.extend_from_slice(&chunk);
    }
    let value: Value =
        serde_json::from_slice(&body).map_err(|_| Failure("invalid_provider_metadata"))?;
    if value.get("name").and_then(Value::as_str) != Some(settings.model.as_str()) {
        return Err(Failure("invalid_provider_metadata"));
    }
    let model_deprecated = value.get("is_deprecated").and_then(Value::as_bool);
    let available = value["endpoints"]
        .as_array()
        .is_some_and(|v| v.iter().any(|v| v == "chat"))
        && model_deprecated != Some(true);
    Ok(Status {
        provider: "cohere",
        model: settings.model,
        key_authenticated: true,
        model_available: available,
        model_deprecated,
        generation_flags_enabled: settings.generation_flags_enabled,
        candidate_data_authorized: settings.candidate_data_authorized,
        generation_performed: false,
    })
}
pub async fn check(path: &Path) -> Result<Status> {
    let settings = Settings::parse(&private_values(path)?)?;
    let endpoint = format!("https://api.cohere.com/v1/models/{}", settings.model);
    metadata(settings, &endpoint).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        Router,
        extract::{Request, State},
        http::StatusCode,
        response::IntoResponse,
        routing::get,
    };
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    fn values() -> BTreeMap<String, String> {
        BTreeMap::from([
            (
                "COHERE_API_KEY".into(),
                "fictional-key-secret-canary".into(),
            ),
            ("COHERE_MODEL".into(), "command-a-plus-05-2026".into()),
        ])
    }
    #[test]
    fn metadata_does_not_silently_enable_generation_or_accept_arbitrary_models() {
        let mut config = values();
        let settings = Settings::parse(&config).unwrap();
        assert!(!settings.generation_flags_enabled);
        assert!(!settings.candidate_data_authorized);
        config.insert(
            "COHERE_MODEL".into(),
            "https://untrusted.example/model".into(),
        );
        assert_eq!(
            Settings::parse(&config).err().map(|f| f.0),
            Some("model_unavailable")
        );
        config.remove("COHERE_MODEL");
        config.insert("COHERE_API_KEY".into(), "secret\nheader".into());
        assert_eq!(
            Settings::parse(&config).err().map(|f| f.0),
            Some("llm_not_configured")
        );
    }
    async fn fixture(
        code: StatusCode,
        body: String,
    ) -> (String, tokio::task::JoinHandle<()>, Arc<AtomicUsize>) {
        let count = Arc::new(AtomicUsize::new(0));
        let state = (code, body, count.clone());
        async fn handler(
            State((code, body, count)): State<(StatusCode, String, Arc<AtomicUsize>)>,
            request: Request,
        ) -> axum::response::Response {
            assert_eq!(request.method(), "GET");
            assert_eq!(
                request.headers()["authorization"],
                "Bearer fictional-key-secret-canary"
            );
            assert!(request.headers().get("content-type").is_none());
            count.fetch_add(1, Ordering::SeqCst);
            (
                code,
                [("location", "http://127.0.0.1:1/never-follow")],
                body,
            )
                .into_response()
        }
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(
                listener,
                Router::new()
                    .route("/v1/models/command-a-plus-05-2026", get(handler))
                    .with_state(state),
            )
            .await
            .unwrap();
        });
        (
            format!("http://{address}/v1/models/command-a-plus-05-2026"),
            server,
            count,
        )
    }
    #[tokio::test(flavor = "current_thread")]
    async fn official_metadata_shape_is_sanitized_without_generation() {
        let (url,server,count)=fixture(StatusCode::OK,r#"{"name":"command-a-plus-05-2026","endpoints":["chat"],"is_deprecated":false,"private_metadata":"do-not-output-canary"}"#.into()).await;
        let result = metadata(Settings::parse(&values()).unwrap(), &url)
            .await
            .unwrap();
        let value = serde_json::to_string(&result).unwrap();
        assert!(result.key_authenticated && result.model_available);
        assert!(!result.generation_performed && !result.generation_flags_enabled);
        assert!(!value.contains("secret-canary") && !value.contains("do-not-output-canary"));
        assert_eq!(count.load(Ordering::SeqCst), 1);
        server.abort();
    }
    #[tokio::test(flavor = "current_thread")]
    async fn optional_deprecation_metadata_is_reported_without_inventing_a_deprecation() {
        for deprecated in [None, Some(false), Some(true)] {
            let mut body =
                serde_json::json!({"name":"command-a-plus-05-2026","endpoints":["chat"]});
            if let Some(value) = deprecated {
                body["is_deprecated"] = serde_json::json!(value);
            }
            let (url, server, _) = fixture(StatusCode::OK, body.to_string()).await;
            let status = metadata(Settings::parse(&values()).unwrap(), &url)
                .await
                .unwrap();
            assert_eq!(status.model_deprecated, deprecated);
            assert_eq!(status.model_available, deprecated != Some(true));
            server.abort();
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn failures_redirects_oversized_and_mismatched_responses_never_retry_or_expose_bodies() {
        for (code, body, error) in [
            (
                StatusCode::UNAUTHORIZED,
                "private-secret-body".into(),
                "provider_authentication",
            ),
            (StatusCode::FOUND, "".into(), "provider_error"),
            (
                StatusCode::TOO_MANY_REQUESTS,
                "private-secret-body".into(),
                "rate_limited",
            ),
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                "private-secret-body".into(),
                "provider_error",
            ),
            (StatusCode::OK, "x".repeat(65537), "provider_response_size"),
            (StatusCode::OK, "{}".into(), "invalid_provider_metadata"),
        ] {
            let (url, server, count) = fixture(code, body).await;
            assert_eq!(
                metadata(Settings::parse(&values()).unwrap(), &url)
                    .await
                    .err(),
                Some(Failure(error))
            );
            assert_eq!(count.load(Ordering::SeqCst), 1);
            server.abort();
        }
    }
}
