//! Bounded loopback owner API. Models and extension clients cannot call lifecycle controls.
use crate::{
    Failure, Result,
    configuration::Configuration,
    contracts::Limits,
    knowledge::ProfilePin,
    lifecycle::{self, Action, Mode},
    worker::Wake,
};
use axum::{
    Router,
    body::to_bytes,
    extract::{ConnectInfo, Request, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{PgConnection, Row};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use subtle::ConstantTimeEq;
use tokio::sync::{Mutex, Semaphore};
use uuid::Uuid;

pub struct Api {
    config: Arc<Configuration>,
    connection: Mutex<PgConnection>,
    wake: Wake,
    requests: Semaphore,
}
impl Api {
    pub fn new(config: Arc<Configuration>, connection: PgConnection, wake: Wake) -> Arc<Self> {
        Arc::new(Self {
            config,
            connection: Mutex::new(connection),
            wake,
            requests: Semaphore::new(8),
        })
    }
}
pub fn router(api: Arc<Api>) -> Router {
    Router::new().fallback(handle).with_state(api)
}

pub async fn readiness(connection: &mut PgConnection, config: &Configuration) -> Result<()> {
    let row=sqlx::query("SELECT current_database() AS database,current_schema() AS schema,current_user AS role,to_regclass('rust_agent_runs') IS NOT NULL AND to_regclass('rust_agent_events') IS NOT NULL AND to_regclass('rust_agent_control_events') IS NOT NULL AND to_regclass('candidate_profiles') IS NOT NULL AND to_regclass('owner_preferences') IS NOT NULL AND to_regclass('jobs') IS NOT NULL AND to_regclass('companies') IS NOT NULL AND to_regclass('application_packets') IS NOT NULL AS tables")
        .fetch_one(&mut *connection).await.map_err(|_|Failure("agent_schema_unavailable"))?;
    if row.get::<String, _>("database") != config.database
        || row.get::<Option<String>, _>("schema").as_deref() != Some(config.schema.as_str())
        || row.get::<String, _>("role") != config.role
        || !row.get::<bool, _>("tables")
    {
        return Err(Failure("agent_database_target_mismatch"));
    }
    sqlx::query("SELECT decision_calls FROM rust_agent_events LIMIT 0")
        .execute(&mut *connection)
        .await
        .map_err(|_| Failure("agent_schema_unavailable"))?;
    sqlx::query("SELECT question_checked_at FROM rust_agent_runs LIMIT 0")
        .execute(&mut *connection)
        .await
        .map_err(|_| Failure("agent_schema_unavailable"))?;
    lifecycle::control(connection).await?;
    Ok(())
}
fn single<'a>(headers: &'a HeaderMap, key: &str) -> Option<&'a str> {
    let mut entries = headers.get_all(key).iter();
    let value = entries.next()?.to_str().ok()?;
    if entries.next().is_some() {
        None
    } else {
        Some(value)
    }
}
fn authorize(request: &Request, config: &Configuration) -> Result<()> {
    let peer = request
        .extensions()
        .get::<ConnectInfo<SocketAddr>>()
        .ok_or(Failure("owner_peer_denied"))?
        .0;
    if !peer.ip().is_loopback() {
        return Err(Failure("owner_peer_denied"));
    }
    let headers = request.headers();
    let host = single(headers, "host").ok_or(Failure("owner_host_denied"))?;
    let authority = host
        .parse::<axum::http::uri::Authority>()
        .map_err(|_| Failure("owner_host_denied"))?;
    if host.contains(['@', '/', '?', '#'])
        || !config.hosts.iter().any(|h| {
            h.eq_ignore_ascii_case(host)
                || (!h.contains(':') && h.eq_ignore_ascii_case(authority.host()))
        })
    {
        return Err(Failure("owner_host_denied"));
    }
    if headers.contains_key("origin")
        && single(headers, "origin").is_none_or(|value| !config.origins.iter().any(|s| s == value))
    {
        return Err(Failure("owner_origin_denied"));
    }
    if request.method() == axum::http::Method::GET && request.uri().path() == "/health" {
        return Ok(());
    }
    if headers.contains_key("x-agent-client") {
        return Err(Failure("owner_client_required"));
    }
    if config.require_tls
        && !(config.trust_proxy && single(headers, "x-forwarded-proto") == Some("https"))
    {
        return Err(Failure("owner_api_tls_required"));
    }
    let token = single(headers, "authorization")
        .and_then(|s| s.strip_prefix("Bearer "))
        .ok_or(Failure("owner_authentication_required"))?;
    if !bool::from(token.as_bytes().ct_eq(config.token.as_bytes())) {
        return Err(Failure("owner_authentication_required"));
    }
    Ok(())
}
async fn handle(State(api): State<Arc<Api>>, request: Request) -> Response {
    let Ok(_permit) = api.requests.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"error":"owner_api_busy"}),
        );
    };
    if let Err(error) = authorize(&request, &api.config) {
        return failure(error);
    }
    let method = request.method().as_str().to_owned();
    let path = request.uri().path().to_owned();
    if method == "GET" && path == "/health" {
        return reply(
            StatusCode::OK,
            json!({"alive":true,"scope":"saved_job_review_no_application_dispatch"}),
        );
    }
    if request.uri().query().is_some() {
        return failure(Failure("query_parameters_not_supported"));
    }
    let body = match tokio::time::timeout(
        Duration::from_secs(20),
        to_bytes(request.into_body(), 65536),
    )
    .await
    {
        Ok(Ok(body)) => body,
        Ok(Err(_)) => {
            return reply(
                StatusCode::PAYLOAD_TOO_LARGE,
                json!({"error":"owner_request_too_large"}),
            );
        }
        Err(_) => {
            return reply(
                StatusCode::REQUEST_TIMEOUT,
                json!({"error":"owner_request_timeout"}),
            );
        }
    };
    let mut connection = api.connection.lock().await;
    let result = dispatch(&api, &mut connection, &method, &path, &body).await;
    match result {
        Ok(data) => reply(StatusCode::OK, data),
        Err(error) => failure(error),
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Intake {
    request_id: Uuid,
    #[serde(default)]
    limits: Limits,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlRequest {
    expected_revision: i64,
    mode: Mode,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RunControl {
    expected_revision: i64,
    action: Action,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Resolution {
    expected_revision: i64,
    profile: ProfilePin,
}
fn decode<T: serde::de::DeserializeOwned>(body: &[u8]) -> Result<T> {
    serde_json::from_slice(body).map_err(|_| Failure("invalid_owner_request"))
}
fn uuid(value: &str) -> Result<Uuid> {
    value.parse().map_err(|_| Failure("invalid_owner_request"))
}
async fn dispatch(
    api: &Api,
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    body: &[u8],
) -> Result<Value> {
    let parts = path
        .split('/')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>();
    // Only exact paths: repeated/trailing separators must not create aliases.
    if format!("/{}", parts.join("/")) != path {
        return Err(Failure("owner_route_not_found"));
    }
    match (method, parts.as_slice()) {
        ("GET", ["ready"]) => {
            readiness(connection, &api.config).await?;
            Ok(json!({"ready":true,"scope":"saved_job_review_no_application_dispatch"}))
        }
        ("GET", ["api", "v1", "rust-agent", "control"]) => {
            Ok(serde_json::to_value(lifecycle::control(connection).await?)
                .map_err(|_| Failure("invalid_control_response"))?)
        }
        ("PUT", ["api", "v1", "rust-agent", "control"]) => {
            let input: ControlRequest = decode(body)?;
            let control =
                lifecycle::set_control(connection, input.expected_revision, input.mode).await?;
            api.wake.controls_changed();
            Ok(serde_json::to_value(control).map_err(|_| Failure("invalid_control_response"))?)
        }
        ("GET", ["api", "v1", "rust-agent", "runs"]) => {
            Ok(json!({"runs":lifecycle::listing(connection).await?}))
        }
        ("POST", ["api", "v1", "rust-agent", "runs"]) => {
            let input: Intake = decode(body)?;
            let stored = lifecycle::intake(connection, input.request_id, input.limits).await?;
            api.wake.work_available();
            Ok(lifecycle::summary(&stored))
        }
        ("GET", ["api", "v1", "rust-agent", "questions"]) => {
            Ok(json!({"questions":lifecycle::pending_questions(connection).await?}))
        }
        ("GET", ["api", "v1", "rust-agent", "runs", id]) => Ok(lifecycle::summary(
            &lifecycle::load(connection, uuid(id)?).await?,
        )),
        ("GET", ["api", "v1", "rust-agent", "runs", id, "events"]) => {
            Ok(json!({"events":lifecycle::events(connection,uuid(id)?).await?}))
        }
        ("POST", ["api", "v1", "rust-agent", "runs", id, "control"]) => {
            let input: RunControl = decode(body)?;
            let saved = lifecycle::control_run(
                connection,
                uuid(id)?,
                input.expected_revision,
                input.action,
            )
            .await?;
            api.wake.run_changed(saved.run.id);
            Ok(lifecycle::summary(&saved))
        }
        (
            "POST",
            [
                "api",
                "v1",
                "rust-agent",
                "runs",
                id,
                "questions",
                question,
                "resolve",
            ],
        ) => {
            let input: Resolution = decode(body)?;
            let saved = lifecycle::resolve_question(
                connection,
                uuid(id)?,
                input.expected_revision,
                uuid(question)?,
                &input.profile,
            )
            .await?;
            api.wake.work_available();
            Ok(lifecycle::summary(&saved))
        }
        _ => Err(Failure("owner_route_not_found")),
    }
}
fn failure(error: Failure) -> Response {
    let code = match error.0 {
        "owner_authentication_required" => StatusCode::UNAUTHORIZED,
        "owner_peer_denied"
        | "owner_host_denied"
        | "owner_origin_denied"
        | "owner_client_required" => StatusCode::FORBIDDEN,
        "owner_api_tls_required" => StatusCode::UPGRADE_REQUIRED,
        "agent_run_not_found" | "owner_route_not_found" => StatusCode::NOT_FOUND,
        "agent_revision_conflict"
        | "agent_control_revision_conflict"
        | "agent_request_key_conflict"
        | "agent_question_not_pending"
        | "owner_fact_not_confirmed"
        | "verified_profile_context_changed"
        | "verified_profile_identity_changed"
        | "agent_reconciliation_required"
        | "invalid_agent_control" => StatusCode::CONFLICT,
        "agent_database_error"
        | "agent_schema_unavailable"
        | "invalid_worker_control"
        | "agent_database_target_mismatch" => StatusCode::SERVICE_UNAVAILABLE,
        _ => StatusCode::BAD_REQUEST,
    };
    reply(code, json!({"error":error.0}))
}
fn reply(status: StatusCode, data: Value) -> Response {
    let mut response = (status, axum::Json(data)).into_response();
    for (key, value) in [
        ("cache-control", "private, no-store"),
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", "no-referrer"),
    ] {
        response.headers_mut().insert(
            axum::http::HeaderName::from_static(key),
            axum::http::HeaderValue::from_static(value),
        );
    }
    response
}

#[cfg(test)]
mod tests {
    use super::*;
    fn config() -> Configuration {
        Configuration::from_values(&std::collections::BTreeMap::from([
            ("ENVIRONMENT".into(), "testing".into()),
            ("RUST_RUNTIME_FIXTURE".into(), "true".into()),
            (
                "DATABASE_URL".into(),
                "postgresql://rust_agent_fixture@127.0.0.1:54321/rust_agent_fixture".into(),
            ),
            (
                "JOB_AGENT_API_TOKEN".into(),
                "0123456789abcdefghijklmnopqrstuvwxyzABCDEF".into(),
            ),
            ("API_REQUIRE_TLS".into(), "false".into()),
        ]))
        .unwrap()
    }
    fn request(config: &Configuration) -> Request {
        let mut request = Request::builder()
            .uri("/ready")
            .header("host", "127.0.0.1:8011")
            .header("authorization", format!("Bearer {}", config.token))
            .body(axum::body::Body::empty())
            .unwrap();
        request.extensions_mut().insert(ConnectInfo(
            "127.0.0.1:12345".parse::<SocketAddr>().unwrap(),
        ));
        request
    }
    #[test]
    fn owner_authentication_rejects_duplicate_credentials_origins_and_extension_clients() {
        let config = config();
        assert!(authorize(&request(&config), &config).is_ok());
        let mut duplicate = request(&config);
        duplicate.headers_mut().append(
            "authorization",
            axum::http::HeaderValue::from_static("Bearer second"),
        );
        assert_eq!(
            authorize(&duplicate, &config),
            Err(Failure("owner_authentication_required"))
        );
        let mut origin = request(&config);
        origin.headers_mut().insert(
            "origin",
            axum::http::HeaderValue::from_static("https://untrusted.example.net"),
        );
        assert_eq!(
            authorize(&origin, &config),
            Err(Failure("owner_origin_denied"))
        );
        let mut extension = request(&config);
        extension.headers_mut().insert(
            "x-agent-client",
            axum::http::HeaderValue::from_static("extension"),
        );
        assert_eq!(
            authorize(&extension, &config),
            Err(Failure("owner_client_required"))
        );
        let mut rebound = request(&config);
        rebound.headers_mut().insert(
            "host",
            axum::http::HeaderValue::from_static("attacker.example.net"),
        );
        assert_eq!(
            authorize(&rebound, &config),
            Err(Failure("owner_host_denied"))
        );
    }
    #[test]
    fn https_request_target_does_not_spoof_tls_and_proxy_trust_is_explicit() {
        let mut config = config();
        config.require_tls = true;
        let mut request = request(&config);
        *request.uri_mut() = "https://127.0.0.1/ready".parse().unwrap();
        request.headers_mut().insert(
            "x-forwarded-proto",
            axum::http::HeaderValue::from_static("https"),
        );
        assert_eq!(
            authorize(&request, &config),
            Err(Failure("owner_api_tls_required"))
        );
        config.trust_proxy = true;
        assert!(authorize(&request, &config).is_ok());
        request.headers_mut().append(
            "x-forwarded-proto",
            axum::http::HeaderValue::from_static("http"),
        );
        assert_eq!(
            authorize(&request, &config),
            Err(Failure("owner_api_tls_required"))
        );
    }
    #[test]
    fn strict_requests_cannot_smuggle_authority_or_personal_answers() {
        assert!(
            decode::<Intake>(
                br#"{"request_id":"00000000-0000-0000-0000-000000000001","submit":true}"#
            )
            .is_err()
        );
        assert!(decode::<Resolution>(br#"{"expected_revision":1,"profile":{"id":"00000000-0000-0000-0000-000000000002","version":4},"answer":30}"#).is_err());
        assert!(
            decode::<ControlRequest>(
                br#"{"expected_revision":1,"mode":"RUNNING","mode":"STOPPED"}"#
            )
            .is_err()
        );
    }
}
