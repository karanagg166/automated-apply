//! Bounded loopback owner API. Models and extension clients cannot call lifecycle controls.
use crate::{
    Failure, Result,
    configuration::Configuration,
    contracts::{Limits, Role, ToolName},
    knowledge::ProfilePin,
    lifecycle::{self, Action, Mode},
    recovery::{self, Backoff},
    worker::Wake,
};
mod accounts;
mod boundary;
mod contact_io;
mod discovery;
mod document_io;
mod errors;
mod gmail_accounts_io;
mod gmail_legacy_io;
mod gmail_workspace_io;
mod outreach_io;
mod owner_http;
mod startup_io;
use boundary::*;
use document_io::{ResumeIo, generation_dispatch, resume_io_dispatch};
mod profile;
mod queue_generation;
use axum::{
    Router,
    body::to_bytes,
    extract::{ConnectInfo, Request, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use errors::{failure, profile_failure, reply};
use profile::{candidate_resource_dispatch, missing_dispatch, profile_dispatch};
pub use queue_generation::serve as serve_queue_generation;
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Row};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use subtle::ConstantTimeEq;
use tokio::sync::{Mutex, Semaphore};
use uuid::Uuid;

pub struct Api {
    config: Arc<Configuration>,
    connection: Mutex<ControlConnection>,
    wake: Wake,
    requests: Semaphore,
    long_request: Semaphore,
    public_request: Semaphore,
}
struct ControlConnection {
    value: Option<PgConnection>,
    backoff: Backoff,
}
impl Api {
    pub fn new(config: Arc<Configuration>, connection: PgConnection, wake: Wake) -> Arc<Self> {
        Arc::new(Self {
            config,
            connection: Mutex::new(ControlConnection {
                value: Some(connection),
                backoff: Backoff::default(),
            }),
            wake,
            requests: Semaphore::new(8),
            long_request: Semaphore::new(1),
            public_request: Semaphore::new(1),
        })
    }
}
pub fn router(api: Arc<Api>) -> Router {
    Router::new().fallback(owner_http::handle).with_state(api)
}
/// Run after HTTP handlers and execution have drained. Reconcile a failed control
/// connection once, then persist pause; never report a clean stop without confirmation.
pub async fn quiesce(api: &Api) -> Result<()> {
    let mut state = api.connection.lock().await;
    if let Some(connection) = state.value.as_mut()
        && pause(connection).await.is_ok()
    {
        return Ok(());
    }
    if let Some(connection) = state.value.take() {
        recovery::close(connection).await;
    }
    let mut connection = api.config.connect(false).await?;
    readiness(&mut connection, &api.config).await?;
    let result = pause(&mut connection).await;
    state.value = Some(connection);
    result
}
async fn pause(connection: &mut PgConnection) -> Result<()> {
    crate::execution::schedule::pause(connection).await?;
    let control = lifecycle::control(connection).await?;
    if control.mode == Mode::Running {
        lifecycle::set_control(connection, control.revision, Mode::Paused).await?;
    }
    sqlx::query("UPDATE rust_agent_control SET heartbeat_at=NULL WHERE key='primary'")
        .execute(connection)
        .await
        .map_err(|_| Failure("agent_database_error"))?;
    Ok(())
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
    sqlx::query(
        "SELECT graph_node,graph_iteration,approval_required FROM rust_agent_events LIMIT 0",
    )
    .execute(&mut *connection)
    .await
    .map_err(|_| Failure("agent_schema_unavailable"))?;
    Ok(())
}
struct OwnerReply {
    data: Value,
    status: StatusCode,
    etag: Option<String>,
}
/// A single bounded request-scoped API-role connection keeps control/Stop responsive.
/// It is closed after the response computation; there is no additional pool or retry.
fn supplied_limits<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Option<Limits>, D::Error> {
    Limits::deserialize(deserializer).map(Some)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Intake {
    request_id: Uuid,
    #[serde(default, deserialize_with = "supplied_limits")]
    limits: Option<Limits>,
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
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ApprovalDecision {
    expected_revision: i64,
    decision: crate::graph::Decision,
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
    if let Some(result) =
        crate::tool_api::route(&api.config, connection, method, &parts, body).await
    {
        return result;
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
        ("GET", ["api", "v1", "rust-agent", "capabilities"]) => {
            let policy = api.config.model_policy();
            let limits = policy.recommended_limits();
            let tools = ToolName::ALL.into_iter().map(|name| {
                let status = match name {
                    ToolName::SearchJobs|ToolName::RankJobs|ToolName::VerifiedContext|ToolName::ApplicationHistory => "available",
                    ToolName::NotifyTelegram if api.config.telegram.is_some() => "available",
                    ToolName::NotifyTelegram => "disabled",
                    _ => "not_migrated",
                };
                let roles=[Role::Discovery,Role::Matching,Role::Answers,Role::Review,Role::Execution].into_iter().filter(|role| name.allowed(*role)).collect::<Vec<_>>();
                json!({"name":name,"description":name.description(),"roles":roles,"repeatable":name.repeatable(),"status":status})
            }).collect::<Vec<_>>();
            Ok(
                json!({"model_roles":policy.roles(),"model_policy":policy,"tools":tools,"review_model":api.config.review_model(),"recommended_limits":limits,"application_dispatch":false,"graph":crate::graph::MERMAID,"human_decisions":["approve","reject","request_changes"]}),
            )
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
            let policy = api.config.model_policy();
            let limits = input.limits.unwrap_or_else(|| {
                if api.config.models.is_some() {
                    let mut limits = policy.recommended_limits();
                    limits.human_review = false;
                    limits
                } else {
                    Limits::default()
                }
            });
            let stored =
                lifecycle::intake_policy(connection, input.request_id, limits, Some(policy))
                    .await?;
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
        ("GET", ["api", "v1", "rust-agent", "runs", id, "plan"]) => {
            let stored = lifecycle::load(connection, uuid(id)?).await?;
            Ok(crate::graph::preview(&stored.run, stored.revision))
        }
        ("POST", ["api", "v1", "rust-agent", "runs", id, "approvals", approval]) => {
            let input: ApprovalDecision = decode(body)?;
            let saved = lifecycle::approve(
                connection,
                uuid(id)?,
                input.expected_revision,
                uuid(approval)?,
                input.decision,
                crate::graph::Actor::OwnerApi,
            )
            .await?;
            api.wake.run_changed(saved.run.id);
            api.wake.work_available();
            Ok(lifecycle::summary(&saved))
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
    fn browser_oauth_callback_exception_retains_transport_checks_and_is_get_only() {
        let mut config = config();
        let mut callback = request(&config);
        *callback.uri_mut() = crate::mailboxes::routes::CALLBACK.parse().unwrap();
        callback.headers_mut().remove("authorization");
        assert!(authorize(&callback, &config).is_ok());
        *callback.method_mut() = axum::http::Method::POST;
        assert_eq!(
            authorize(&callback, &config),
            Err(Failure("owner_authentication_required"))
        );
        *callback.method_mut() = axum::http::Method::GET;
        config.require_tls = true;
        assert_eq!(
            authorize(&callback, &config),
            Err(Failure("owner_api_tls_required"))
        );
        config.require_tls = false;
        callback
            .headers_mut()
            .insert("origin", "https://untrusted.example.net".parse().unwrap());
        assert_eq!(
            authorize(&callback, &config),
            Err(Failure("owner_origin_denied"))
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
        for body in [br#"{"request_id":"00000000-0000-0000-0000-000000000001","limits":null}"#.as_slice(),br#"{"request_id":"00000000-0000-0000-0000-000000000001","model_policy":{"provider":"cohere","roles":["execution"]}}"#.as_slice()] {assert!(decode::<Intake>(body).is_err());}
        assert!(decode::<Resolution>(br#"{"expected_revision":1,"profile":{"id":"00000000-0000-0000-0000-000000000002","version":4},"answer":30}"#).is_err());
        assert!(
            decode::<ControlRequest>(
                br#"{"expected_revision":1,"mode":"RUNNING","mode":"STOPPED"}"#
            )
            .is_err()
        );
    }
}
