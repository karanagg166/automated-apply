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
use axum::{
    Router,
    body::to_bytes,
    extract::{ConnectInfo, Request, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
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
        })
    }
}
pub fn router(api: Arc<Api>) -> Router {
    Router::new().fallback(handle).with_state(api)
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
fn single<'a>(headers: &'a HeaderMap, key: &str) -> Option<&'a str> {
    let mut entries = headers.get_all(key).iter();
    let value = entries.next()?.to_str().ok()?;
    if entries.next().is_some() {
        None
    } else {
        Some(value)
    }
}
fn saved_match_route(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/jobs/")
        .and_then(|tail| tail.strip_suffix("/match"))
        .filter(|id| !id.is_empty() && !id.contains('/'))
}
fn profile_route(path: &str) -> bool {
    path == "/api/v1/profile"
        || saved_match_route(path).is_some()
        || path == "/api/v1/local-agent/profile-confirmation"
        || resource_inspection(path)
        || candidate_resource_route(path)
        || draft_route(path)
        || missing_route(path)
        || path == "/api/v1/application-answers/generate"
        || path == "/api/v1/application-answers/reuse-approvals"
        || resume_route(path).is_some()
        || crate::notifications::route(path).is_some()
        || crate::job_catalog::route(path).is_some()
        || crate::packet_service::route(path).is_some()
}
fn resume_route(path: &str) -> Option<(&str, &str)> {
    let tail = path.strip_prefix("/api/v1/dashboard/resumes")?;
    if tail.is_empty() {
        return Some(("", ""));
    }
    let tail = tail.strip_prefix('/')?;
    let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
    (!id.is_empty() && matches!(action, "" | "confirm")).then_some((id, action))
}
fn resume_label(query: Option<&str>) -> Result<String> {
    let Some(query) = query else {
        return Ok("Resume".into());
    };
    let raw = query
        .strip_prefix("label=")
        .filter(|s| !s.contains('&') && s.len() <= 2400)
        .ok_or(Failure("invalid_resume_label"))?;
    let raw = raw.replace('+', " ");
    let label = percent_encoding::percent_decode_str(&raw)
        .decode_utf8()
        .map_err(|_| Failure("invalid_resume_label"))?
        .into_owned();
    if label.is_empty() || label.chars().count() > 200 {
        return Err(Failure("invalid_resume_label"));
    }
    Ok(label)
}
fn missing_item(path: &str) -> Option<(&str, &str)> {
    let tail = path.strip_prefix("/api/v1/application-answers/missing/")?;
    let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
    (!id.is_empty() && matches!(action, "" | "approve" | "history")).then_some((id, action))
}
fn missing_route(path: &str) -> bool {
    path == "/api/v1/application-answers/missing" || missing_item(path).is_some()
}
fn paginated(path: &str) -> bool {
    matches!(
        path,
        "/api/v1/candidate/resources"
            | "/api/v1/candidate/evidence"
            | "/api/v1/application-answers/drafts"
            | "/api/v1/application-answers/missing"
            | crate::notifications::INBOX
    ) || missing_item(path).is_some_and(|(_, action)| action == "history")
}
fn draft_id(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/application-answers/drafts/")
        .filter(|s| !s.is_empty() && !s.contains('/'))
}
fn draft_route(path: &str) -> bool {
    path == "/api/v1/application-answers/drafts"
        || draft_id(path).is_some()
        || draft_action(path).is_some()
}
fn draft_action(path: &str) -> Option<(&str, &str)> {
    let tail = path.strip_prefix("/api/v1/application-answers/drafts/")?;
    let (id, action) = tail.split_once('/')?;
    (!id.is_empty()
        && matches!(
            action,
            "approve-reuse" | "revoke-reuse" | "opportunity-evidence"
        ))
    .then_some((id, action))
}
fn candidate_resource_route(path: &str) -> bool {
    matches!(
        path,
        "/api/v1/candidate/resources"
            | "/api/v1/candidate/evidence"
            | "/api/v1/candidate/resources/resolve"
    ) || evidence_id(path).is_some()
}
fn evidence_id(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/candidate/evidence/")
        .filter(|id| !id.is_empty() && !id.contains('/'))
}
fn resource_page(path: &str, method: &str, query: Option<&str>) -> Result<(i64, i64)> {
    let mut page = (0, 25);
    let invalid = Failure(if path == crate::notifications::INBOX {
        "invalid_notification_page"
    } else {
        "invalid_resource_page"
    });
    let Some(query) = query else {
        return Ok(page);
    };
    if !paginated(path) || method != "GET" || query.len() > 256 {
        return Err(Failure("query_parameters_not_supported"));
    }
    let mut seen = std::collections::HashSet::new();
    for (key, value) in reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
        .map_err(|_| invalid)?
        .query_pairs()
    {
        if !seen.insert(key.to_string()) {
            return Err(invalid);
        }
        match key.as_ref() {
            "offset" => {
                page.0 = crate::profile_contract::pagination_integer(json!(value), 0, 100000)
                    .map_err(|_| invalid)?
            }
            "limit" => {
                if path == crate::notifications::INBOX {
                    return Err(invalid);
                }
                page.1 = crate::profile_contract::pagination_integer(json!(value), 1, 100)
                    .map_err(|_| invalid)?
            }
            _ => return Err(invalid),
        }
    }
    Ok(page)
}
fn resource_inspection(path: &str) -> bool {
    matches!(
        path,
        "/api/v1/rust-agent/profile-readiness" | "/api/v1/rust-agent/resume-selection"
    )
}
fn selected_resource(path: &str, method: &str, query: Option<&str>) -> Result<Option<Uuid>> {
    let Some(query) = query else {
        return Ok(None);
    };
    if path == "/api/v1/dashboard/resumes" && method == "POST" {
        resume_label(Some(query))?;
        return Ok(None);
    }
    if paginated(path) && method == "GET" {
        return Ok(None);
    }
    if crate::job_catalog::route(path).is_some()
        || crate::packet_service::route(path).is_some()
        || (saved_match_route(path).is_some() && method == "GET")
    {
        return Ok(None);
    }
    if path != "/api/v1/rust-agent/resume-selection" || method != "GET" {
        return Err(Failure("query_parameters_not_supported"));
    }
    let raw = query
        .strip_prefix("selected_id=")
        .filter(|s| !s.contains('&') && s.len() <= 100)
        .ok_or(Failure("invalid_resource_selection"))?;
    raw.parse()
        .map(Some)
        .map_err(|_| Failure("invalid_resource_selection"))
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
        .and_then(|s| {
            if profile_route(request.uri().path()) {
                s.split_once(' ')
                    .filter(|(scheme, _)| scheme.eq_ignore_ascii_case("bearer"))
                    .map(|(_, token)| token)
            } else {
                s.strip_prefix("Bearer ")
            }
        })
        .ok_or(Failure("owner_authentication_required"))?;
    if !bool::from(token.as_bytes().ct_eq(config.token.as_bytes())) {
        return Err(Failure("owner_authentication_required"));
    }
    Ok(())
}
async fn handle(State(api): State<Arc<Api>>, request: Request) -> Response {
    let is_profile = profile_route(request.uri().path());
    let fail = |error| {
        if is_profile {
            profile_failure(error)
        } else {
            failure(error)
        }
    };
    let Ok(_permit) = api.requests.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"error":"owner_api_busy"}),
        );
    };
    if let Err(error) = authorize(&request, &api.config) {
        return fail(error);
    }
    let method = request.method().as_str().to_owned();
    let path = request.uri().path().to_owned();
    let packet_query = request.uri().query().map(str::to_owned);
    let job_page = match crate::job_catalog::Page::parse(
        if path == crate::job_catalog::JOBS && method == "GET" {
            request.uri().query()
        } else {
            None
        },
    ) {
        Ok(page) => page,
        Err(error) => return fail(error),
    };
    let pdf_upload = path == "/api/v1/dashboard/resumes" && method == "POST";
    let label = if pdf_upload {
        match resume_label(request.uri().query()) {
            Ok(label) => Some(label),
            Err(error) => return fail(error),
        }
    } else {
        None
    };
    if pdf_upload
        && single(request.headers(), "content-type").and_then(|s| s.split(';').next())
            != Some("application/pdf")
    {
        return fail(Failure("pdf_content_type_required"));
    }
    if method == "GET" && path == "/health" {
        return reply(
            StatusCode::OK,
            json!({"alive":true,"scope":"saved_job_review_no_application_dispatch"}),
        );
    }
    let selected = match selected_resource(&path, &method, request.uri().query()) {
        Ok(selected) => selected,
        Err(error) => return fail(error),
    };
    let page = if paginated(&path) {
        match resource_page(&path, &method, request.uri().query()) {
            Ok(page) => page,
            Err(error) => return fail(error),
        }
    } else {
        (0, 25)
    };
    let if_match = if request.headers().contains_key("if-match") {
        Some(
            single(request.headers(), "if-match")
                .unwrap_or("")
                .to_owned(),
        )
    } else {
        None
    };
    let signature = single(request.headers(), "x-browser-owner-approval").map(str::to_owned);
    let body = match tokio::time::timeout(
        Duration::from_secs(20),
        to_bytes(
            request.into_body(),
            if pdf_upload {
                crate::private_resume::MAX_PDF
            } else {
                65536
            },
        ),
    )
    .await
    {
        Ok(Ok(body)) => body,
        Ok(Err(_)) => {
            return reply(
                StatusCode::PAYLOAD_TOO_LARGE,
                if is_profile {
                    json!({"detail":if pdf_upload{"PDF exceeds 5 MiB"}else{"Profile request exceeds 64 KiB"}})
                } else {
                    json!({"error":"owner_request_too_large"})
                },
            );
        }
        Err(_) => {
            return reply(
                StatusCode::REQUEST_TIMEOUT,
                json!({"error":"owner_request_timeout"}),
            );
        }
    };
    let proof = if method == "POST"
        && (missing_item(&path).is_some_and(|(_, action)| action == "approve")
            || draft_action(&path).is_some_and(|(_, action)| action == "approve-reuse"))
    {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(f64::NAN);
        match api
            .config
            .owner_signing
            .as_ref()
            .ok_or(Failure("owner_approval_unavailable"))
            .and_then(|key| key.verify_at(&path, &body, signature.as_deref().unwrap_or(""), now))
        {
            Ok(proof) => Some(proof),
            Err(error) => return fail(error),
        }
    } else {
        None
    };
    if path == "/api/v1/application-answers/generate" {
        if method != "POST" {
            return fail(Failure("match_method_not_allowed"));
        }
        return generation_dispatch(&api, &body).await;
    }
    if let Some(label) = label {
        return resume_io_dispatch(&api, ResumeIo::Upload(&label, &body)).await;
    }
    if let Some((id, "")) = resume_route(&path)
        && !id.is_empty()
        && method == "GET"
    {
        return match id.parse() {
            Ok(id) => resume_io_dispatch(&api, ResumeIo::Download(id)).await,
            Err(_) => fail(Failure("private_resume_not_found")),
        };
    }
    let mut state = api.connection.lock().await;
    if state.value.is_none() {
        if !state.backoff.remaining().is_zero() {
            return fail(Failure("agent_database_reconnecting"));
        }
        match api.config.connect(false).await {
            Ok(mut connection) => {
                if let Err(error) = readiness(&mut connection, &api.config).await {
                    recovery::close(connection).await;
                    state.backoff.failed();
                    return fail(error);
                }
                state.value = Some(connection);
            }
            Err(error) => {
                state.backoff.failed();
                return fail(error);
            }
        }
    }
    let mut result = match state.value.as_mut() {
        Some(connection) if crate::packet_service::route(&path).is_some() => {
            crate::packet_service::dispatch(
                connection,
                &method,
                &path,
                packet_query.as_deref(),
                &body,
                &api.config.packets,
                &api.config.answers,
            )
            .await
            .map(|(data, created)| OwnerReply {
                data,
                status: if created {
                    StatusCode::CREATED
                } else {
                    StatusCode::OK
                },
                etag: None,
            })
        }
        Some(connection) if crate::job_catalog::route(&path).is_some() => {
            crate::job_catalog::dispatch(connection, &method, &path, &job_page)
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
        }
        Some(connection) if crate::notifications::route(&path).is_some() => {
            crate::notifications::dispatch(connection, &method, &path, page.0)
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
        }
        Some(connection) if resume_route(&path).is_some() => {
            let (id, action) = resume_route(&path).unwrap();
            if id.is_empty() && method == "GET" {
                crate::private_resume::listing(connection)
                    .await
                    .map(|data| OwnerReply {
                        data,
                        status: StatusCode::OK,
                        etag: None,
                    })
            } else if let Ok(id) = id.parse::<Uuid>() {
                if action == "confirm" && method == "POST" {
                    match serde_json::from_slice(&body)
                        .map_err(|_| Failure("invalid_resume_confirmation"))
                        .and_then(crate::private_resume::confirmation)
                    {
                        Ok(input) => crate::private_resume::confirm(
                            connection,
                            id,
                            input,
                            &api.config.resumes,
                        )
                        .await
                        .map(|data| OwnerReply {
                            data,
                            status: StatusCode::OK,
                            etag: None,
                        }),
                        Err(error) => Err(error),
                    }
                } else {
                    Err(Failure("resume_method_not_allowed"))
                }
            } else if id.is_empty() {
                Err(Failure("resume_method_not_allowed"))
            } else {
                Err(Failure("private_resume_not_found"))
            }
        }
        Some(connection) if path == "/api/v1/profile" => {
            profile_dispatch(
                connection,
                &method,
                &body,
                if_match.as_deref(),
                api.config.profile_live,
            )
            .await
        }
        Some(connection) if resource_inspection(&path) => {
            if method != "GET" {
                Err(Failure("resource_read_method_not_allowed"))
            } else {
                crate::resource_store::inspect(
                    connection,
                    selected,
                    path.ends_with("profile-readiness"),
                    api.config.profile_live,
                )
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
            }
        }
        Some(connection) if candidate_resource_route(&path) => {
            candidate_resource_dispatch(connection, &method, &path, &body, page, &api.config).await
        }
        Some(connection) if missing_route(&path) => {
            missing_dispatch(connection, &method, &path, &body, page, proof).await
        }
        Some(connection) if draft_route(&path) => {
            let data = if let Some((id, action)) = draft_action(&path) {
                match id.parse::<Uuid>() {
                    Err(_) => Err(Failure("invalid_answer_draft_review")),
                    Ok(id) => match (method.as_str(), action) {
                        ("POST", "approve-reuse") => {
                            match serde_json::from_slice(&body)
                                .map_err(|_| Failure("invalid_answer_reuse_approval"))
                                .and_then(crate::answer_reuse::approval_input)
                            {
                                Ok(input) => match proof {
                                    Some(proof) => {
                                        crate::answer_reuse::approve(
                                            connection,
                                            id,
                                            input,
                                            proof,
                                            api.config.answers.reuse,
                                            api.config.answers.opportunity,
                                        )
                                        .await
                                    }
                                    None => Err(Failure("owner_approval_required")),
                                },
                                Err(error) => Err(error),
                            }
                        }
                        ("POST", "revoke-reuse") => {
                            crate::answer_reuse::revoke(connection, id).await
                        }
                        ("GET", "opportunity-evidence") => {
                            crate::answer_reuse::opportunity_evidence(connection, id).await
                        }
                        (_, "opportunity-evidence") => {
                            Err(Failure("resource_read_method_not_allowed"))
                        }
                        _ => Err(Failure("match_method_not_allowed")),
                    },
                }
            } else if path == "/api/v1/application-answers/drafts" {
                if method != "GET" {
                    Err(Failure("resource_read_method_not_allowed"))
                } else {
                    crate::answer_store::list(connection, page.0, page.1).await
                }
            } else if method != "PATCH" {
                Err(Failure("evidence_patch_method_not_allowed"))
            } else {
                match (
                    draft_id(&path).unwrap().parse::<Uuid>(),
                    serde_json::from_slice::<crate::answer_store::Review>(&body),
                ) {
                    (Ok(id), Ok(input)) => crate::answer_store::review(connection, id, input).await,
                    _ => Err(Failure("invalid_answer_draft_review")),
                }
            };
            data.map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if path == "/api/v1/application-answers/reuse-approvals" => {
            if method != "GET" {
                Err(Failure("resource_read_method_not_allowed"))
            } else {
                crate::answer_reuse::approvals(
                    connection,
                    api.config.answers.reuse,
                    api.config.owner_signing.is_some(),
                )
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
            }
        }
        Some(connection) if path == "/api/v1/local-agent/profile-confirmation" => {
            if method != "POST" {
                Err(Failure("match_method_not_allowed"))
            } else {
                match serde_json::from_slice::<crate::profile_confirmation::Confirmation>(&body) {
                    Ok(input) => crate::profile_confirmation::confirm(connection, input)
                        .await
                        .map(|data| {
                            api.wake.work_available();
                            OwnerReply {
                                data,
                                status: StatusCode::OK,
                                etag: None,
                            }
                        }),
                    Err(_) => Err(Failure("invalid_profile_confirmation")),
                }
            }
        }
        Some(connection) if saved_match_route(&path).is_some() => {
            if !matches!(method.as_str(), "GET" | "POST") {
                Err(Failure("saved_match_method_not_allowed"))
            } else if let Ok(id) = saved_match_route(&path).unwrap().parse::<Uuid>() {
                let result = if method == "GET" {
                    crate::saved_match::read_calculate(connection, id).await
                } else {
                    crate::saved_match::calculate(connection, id).await
                };
                result
                    .map_err(|error| {
                        if method == "GET"
                            && matches!(error.0, "job_not_found" | "profile_not_found")
                        {
                            Failure("saved_record_not_found")
                        } else {
                            error
                        }
                    })
                    .map(|data| OwnerReply {
                        data,
                        status: StatusCode::OK,
                        etag: None,
                    })
            } else {
                Err(Failure("invalid_job_id"))
            }
        }
        Some(connection) => dispatch(&api, connection, &method, &path, &body)
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            }),
        None => Err(Failure("agent_database_unavailable")),
    };
    // Flush any rollback queued by a rejected operation's transaction Drop before
    // retaining this connection idle. This prevents cross-request lock retention.
    if result.is_err()
        && let Some(connection) = state.value.as_mut()
        && connection.ping().await.is_err()
    {
        result = Err(Failure("profile_database_error"));
    }
    if result
        .as_ref()
        .err()
        .is_some_and(|error| recovery::database_failure(*error))
    {
        if let Some(connection) = state.value.take() {
            recovery::close(connection).await;
        }
        state.backoff.failed();
    } else if result.is_ok() {
        state.backoff.reset();
    }
    match result {
        Ok(result) => {
            let mut response = reply(result.status, result.data);
            if let Some(etag) = result.etag {
                response.headers_mut().insert("etag", etag.parse().unwrap());
            }
            response
        }
        Err(error) => fail(error),
    }
}
fn profile_failure(error: Failure) -> Response {
    if matches!(error.0, "invalid_job_status" | "invalid_catalog_job_record") {
        return reply(
            StatusCode::BAD_REQUEST,
            json!({"detail":"Invalid argument","error_type":"invalid_argument"}),
        );
    }
    let status = failure(error).status();
    let detail = match error.0 {
        "packet_not_found" => "Application packet not found",
        "packet_job_not_found" => "Saved job not found",
        "packet_profile_required" => {
            "Save a candidate profile before persisting an application packet"
        }
        "packet_idempotency_conflict" => {
            "Idempotency key or candidate/job already belongs to a different packet request"
        }
        "packet_storage_conflict" | "packet_serialization_rollback" => {
            "Application data conflict; reload before retrying"
        }
        "packet_multi_select_unavailable" => {
            "Multiple selections require explicit enablement and an installed, permitted database capability; use manual handoff"
        }
        "invalid_packet_preparation" | "invalid_packet_page" | "invalid_packet_id" => {
            "Application preparation request is invalid"
        }
        "packet_method_not_allowed" => "Method Not Allowed",
        "packet_commit_outcome_unknown" => {
            "Packet commit outcome is uncertain; inspect saved packets before retrying"
        }
        "packet_database_error"
        | "invalid_packet_saved_record"
        | "invalid_packet_context_record"
        | "packet_context_inventory_limit"
        | "packet_context_snapshot_required" => "Application storage unavailable",
        "resume_encryption_unavailable" => {
            "Configure the existing dedicated RESUME_ENCRYPTION_KEY before uploading a private resume"
        }
        "private_resume_outcome_unknown" => {
            "Resume operation outcome is uncertain; inspect saved resumes before retrying"
        }
        "private_pdf_integrity_failed" | "private_pdf_checksum_failed" => {
            "Private PDF integrity failed; restore the original PDF and encryption key"
        }
        "drive_resume_review_required" => {
            "Drive imports require the Resume Sync profile-review approval"
        }
        "canonical_resume_changed" => {
            "Canonical resume changed; review the current version before replacing it"
        }
        "private_resume_changed" => "Resume changed; review the current PDF contents",
        "private_resume_binding_invalid" => "Private resume resource binding is invalid",
        "private_resume_not_found" => "Private resume not found",
        "notification_not_found" => "Notification not found",
        "saved_record_not_found" => "Saved record or candidate profile not found",
        "job_shortlist_conflict" => "This job has already progressed beyond shortlisting",
        "job_shortlist_write_conflict" => "Job update was not saved; reload before shortlisting",
        "invalid_job_page" => "Invalid request",
        "invalid_notification_id" | "invalid_notification_record" => "Notification data is invalid",
        "invalid_notification_page" => "Supply offset 0..100000 once; page size is fixed at 50",
        "pdf_content_type_required" => "Use application/pdf",
        "invalid_answer_request" => "Answer request is invalid",
        "generation_outcome_unknown" => {
            "Generation outcome is uncertain; inspect saved drafts and requests before retrying"
        }
        "generation_context_changed" => {
            "Approved facts changed during generation; reload and review before generating again"
        }
        "answer_reuse_disabled" => "Approved answer reuse is disabled",
        "answer_reuse_current_review_required" => {
            "Review the current answer and candidate facts before approving reuse"
        }
        "answer_reuse_unsupported_intent" => {
            "This question requires individual review; no supported reuse intent is established"
        }
        "answer_reuse_job_required" => "Same-job reuse requires a saved job context",
        "answer_reuse_exact_job_required" => {
            "Company or employer evidence can only be reused for the exact saved job"
        }
        "answer_reuse_context_changed" => {
            "Evidence changed or expired; generate and review a fresh answer"
        }
        "invalid_answer_reuse_approval"
        | "invalid_answer_reuse_record"
        | "answer_draft_context_mismatch" => error.0,
        "missing_input_not_found" => "Missing-answer request not found",
        "missing_input_version_conflict"
        | "missing_input_packet_context_mismatch"
        | "missing_input_draft_context_mismatch"
        | "missing_input_identity_collision"
        | "factual_answer_and_evidence_note_required"
        | "missing_input_context_changed_edit_before_approval"
        | "sensitive_answer_not_retained" => error.0,
        "owner_approval_required" => {
            "Submission authorization requires current dashboard owner approval"
        }
        "owner_approval_unavailable" => {
            "Configure a separate dashboard owner approval key before authorizing consent or submission"
        }
        "owner_approval_operation_mismatch" => "Owner approval does not match this exact operation",
        "owner_approval_already_used" => {
            "Owner approval was already used; review again in the dashboard"
        }
        "invalid_missing_input_request" | "invalid_missing_input_record" => error.0,
        "profile_changed_review_current_version" => "profile_changed_review_current_version",
        "invalid_profile_confirmation" => {
            "Review the current profile version and explicitly confirm it"
        }
        "invalid_resource_selection" => "Select a saved resource by its UUID",
        "invalid_resource_record" => "Saved resource is invalid",
        "invalid_resource_input" => "Resource or evidence input is invalid",
        "invalid_resource_page" => "Supply offset 0..100000 and limit 1..100 once each",
        "resource_not_found" => "Resource not found",
        "evidence_not_found" => "Evidence not found",
        "answer_draft_not_found" => "Draft not found",
        "answer_draft_stale" => {
            "Draft is stale; regenerate or correct the profile before reviewing"
        }
        "invalid_answer_draft_record" | "invalid_answer_draft_review" => {
            "Saved answer draft or review is invalid"
        }
        "resource_conflict" => "Duplicate URL or conflicting primary resource",
        "resource_insert_conflict" => {
            "Duplicate URL or conflicting primary resource; update the existing resource or demote its primary first"
        }
        "standard_link_confirmation_required" => {
            "Standard links require explicit user confirmation and are stored only on the profile"
        }
        "standard_link_version_required" => {
            "Supply expected_profile_version to change a standard profile link"
        }
        "resource_inventory_limit" => "Resource inventory exceeds the inspection limit",
        "owner_client_required" => "owner_ui_required",
        "job_not_found" => "Job not found",
        "invalid_job_id" => "Invalid job ID",
        "profile_not_found" => "No candidate profile saved",
        "profile_version_required" => "Supply If-Match with the current profile version",
        "profile_version_conflict" => "Profile version changed; retrieve it before retrying",
        "invalid_profile_version" => "Invalid profile version",
        "profile_version_syntax" => "If-Match must be a quoted positive integer, e.g. \"1\"",
        "owner_authentication_required" => "Invalid or missing bearer token",
        "invalid_profile_input" | "profile_payload_limit" | "invalid_profile_record" => {
            "Resulting profile is invalid or exceeds 64 KiB"
        }
        "fictional_or_placeholder_profile_rejected" => "fictional_or_placeholder_profile_rejected",
        "profile_method_not_allowed"
        | "match_method_not_allowed"
        | "saved_match_method_not_allowed"
        | "resource_list_method_not_allowed"
        | "evidence_patch_method_not_allowed"
        | "resource_read_method_not_allowed" => "Method Not Allowed",
        "missing_item_method_not_allowed" => "Method Not Allowed",
        "profile_database_error" | "agent_database_reconnecting" | "agent_database_unavailable" => {
            "Profile database unavailable; retrieve the current profile before retrying"
        }
        _ => "Profile request rejected",
    };
    let mut response = reply(status, json!({"detail":detail}));
    if error.0 == "saved_match_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET, POST".parse().unwrap());
    }
    if error.0 == "match_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "POST".parse().unwrap());
    }
    if error.0 == "resource_read_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET".parse().unwrap());
    }
    if status == StatusCode::UNAUTHORIZED {
        response
            .headers_mut()
            .insert("www-authenticate", "Bearer".parse().unwrap());
    }
    if error.0 == "resource_list_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET, POST".parse().unwrap());
    }
    if error.0 == "evidence_patch_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "PATCH".parse().unwrap());
    }
    if error.0 == "missing_item_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET, PATCH".parse().unwrap());
    }
    response
}
struct OwnerReply {
    data: Value,
    status: StatusCode,
    etag: Option<String>,
}
/// A single bounded request-scoped API-role connection keeps control/Stop responsive.
/// It is closed after the response computation; there is no additional pool or retry.
async fn generation_dispatch(api: &Api, body: &[u8]) -> Response {
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"An answer generation is already running"}),
        );
    };
    let input = match serde_json::from_slice::<Value>(body) {
        Ok(input) if crate::answer_contract::normalize(input.clone()).is_ok() => input,
        _ => return profile_failure(Failure("invalid_answer_request")),
    };
    let mut connection = match api.config.connect(false).await {
        Ok(connection) => connection,
        Err(error) => return profile_failure(error),
    };
    let result = tokio::time::timeout(Duration::from_secs(40), async {
        readiness(&mut connection, &api.config).await?;
        crate::answer_service::generate(&mut connection, input, &api.config.answers).await
    })
    .await
    .unwrap_or(Err(Failure("generation_outcome_unknown")));
    recovery::close(connection).await;
    match result {
        Ok(data) => reply(StatusCode::OK, data),
        Err(error) => profile_failure(error),
    }
}
enum ResumeIo<'a> {
    Upload(&'a str, &'a [u8]),
    Download(Uuid),
}
enum ResumeOutput {
    Upload(Value),
    Download(Vec<u8>),
}
async fn resume_io_dispatch(api: &Api, input: ResumeIo<'_>) -> Response {
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"A bounded background request is already running"}),
        );
    };
    let mut connection = match api.config.connect(false).await {
        Ok(c) => c,
        Err(error) => return profile_failure(error),
    };
    let result = tokio::time::timeout(Duration::from_secs(40), async {
        readiness(&mut connection, &api.config).await?;
        match input {
            ResumeIo::Upload(label, body) => {
                crate::private_resume::upload(&mut connection, label, body, &api.config.resumes)
                    .await
                    .map(ResumeOutput::Upload)
            }
            ResumeIo::Download(id) => {
                crate::private_resume::download(&mut connection, id, &api.config.resumes)
                    .await
                    .map(ResumeOutput::Download)
            }
        }
    })
    .await
    .unwrap_or(Err(Failure("private_resume_outcome_unknown")));
    recovery::close(connection).await;
    match result {
        Ok(ResumeOutput::Upload(data)) => reply(StatusCode::CREATED, data),
        Ok(ResumeOutput::Download(raw)) => pdf_reply(raw),
        Err(error) => profile_failure(error),
    }
}
fn pdf_reply(raw: Vec<u8>) -> Response {
    let mut response = (StatusCode::OK, raw).into_response();
    for (key, value) in [
        ("content-type", "application/pdf"),
        ("content-disposition", "attachment; filename=\"resume.pdf\""),
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
async fn missing_dispatch(
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    body: &[u8],
    page: (i64, i64),
    proof: Option<crate::owner_proof::Proof>,
) -> Result<OwnerReply> {
    use crate::{missing_contract as contract, missing_store as store};
    let input =
        || serde_json::from_slice(body).map_err(|_| Failure("invalid_missing_input_request"));
    let data = if let Some((id, action)) = missing_item(path) {
        match (method, action) {
            ("GET", "") => store::read(connection, id).await,
            ("PATCH", "") => store::edit(connection, id, contract::normalize_edit(input()?)?).await,
            ("POST", "approve") => {
                store::approve(
                    connection,
                    id,
                    contract::normalize_approve(input()?)?,
                    proof.ok_or(Failure("owner_approval_required"))?,
                )
                .await
            }
            ("GET", "history") => store::history(connection, id, page.0, page.1).await,
            (_, "approve") => Err(Failure("match_method_not_allowed")),
            (_, "history") => Err(Failure("resource_read_method_not_allowed")),
            _ => Err(Failure("missing_item_method_not_allowed")),
        }
    } else {
        match method {
            "GET" => store::list(connection, page.0, page.1).await,
            "POST" => store::create(connection, contract::normalize_create(input()?)?).await,
            _ => Err(Failure("resource_list_method_not_allowed")),
        }
    }?;
    Ok(OwnerReply {
        data,
        status: if method == "POST" && missing_item(path).is_none() {
            StatusCode::CREATED
        } else {
            StatusCode::OK
        },
        etag: None,
    })
}
async fn candidate_resource_dispatch(
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    body: &[u8],
    page: (i64, i64),
    config: &Configuration,
) -> Result<OwnerReply> {
    let result = match (method, path) {
        ("POST", "/api/v1/candidate/resources/resolve") => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::resolve_question(connection, input, &config.resource_defaults)
                .await
        }
        (_, "/api/v1/candidate/resources/resolve") => Err(Failure("match_method_not_allowed")),
        ("GET", "/api/v1/candidate/resources" | "/api/v1/candidate/evidence") => {
            crate::resource_store::list(
                connection,
                path.ends_with("evidence"),
                page.0,
                page.1,
                &config.resource_defaults,
            )
            .await
        }
        ("POST", "/api/v1/candidate/resources") => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::save_resource(connection, input, config.profile_live).await
        }
        ("POST", "/api/v1/candidate/evidence") => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::save_evidence(connection, None, input).await
        }
        ("PATCH", _) if evidence_id(path).is_some() => {
            let id = evidence_id(path)
                .unwrap()
                .parse()
                .map_err(|_| Failure("invalid_resource_selection"))?;
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::save_evidence(connection, Some(id), input).await
        }
        (_, "/api/v1/candidate/resources" | "/api/v1/candidate/evidence") => {
            Err(Failure("resource_list_method_not_allowed"))
        }
        _ => Err(Failure("evidence_patch_method_not_allowed")),
    }?;
    Ok(OwnerReply {
        data: result,
        status: if method == "POST" && path == "/api/v1/candidate/evidence" {
            StatusCode::CREATED
        } else {
            StatusCode::OK
        },
        etag: None,
    })
}
async fn profile_dispatch(
    connection: &mut PgConnection,
    method: &str,
    body: &[u8],
    if_match: Option<&str>,
    live: bool,
) -> Result<OwnerReply> {
    let saved = match method {
        "GET" => crate::profile_store::get(connection).await?,
        "PUT" | "PATCH" => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_profile_input"))?;
            // The legacy HTTP contract validates the DTO before precondition headers.
            let supplied = crate::profile_contract::normalize(
                if method == "PATCH" {
                    crate::profile_contract::Operation::Update
                } else {
                    crate::profile_contract::Operation::Create
                },
                input,
            )?;
            let expected = crate::profile_contract::parse_version(if_match, method == "PATCH")?;
            crate::profile_store::save_normalized(
                connection,
                supplied,
                expected,
                method == "PATCH",
                live,
            )
            .await?
        }
        _ => return Err(Failure("profile_method_not_allowed")),
    };
    Ok(OwnerReply {
        data: saved.value,
        status: if saved.created {
            StatusCode::CREATED
        } else {
            StatusCode::OK
        },
        etag: Some(format!("\"{}\"", saved.version)),
    })
}
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
fn failure(error: Failure) -> Response {
    let code = match error.0 {
        "packet_not_found" | "packet_job_not_found" => StatusCode::NOT_FOUND,
        "packet_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "packet_idempotency_conflict"
        | "packet_storage_conflict"
        | "packet_serialization_rollback" => StatusCode::CONFLICT,
        "packet_profile_required"
        | "packet_multi_select_unavailable"
        | "invalid_packet_preparation"
        | "invalid_packet_page"
        | "invalid_packet_id" => StatusCode::UNPROCESSABLE_ENTITY,
        "packet_database_error"
        | "packet_commit_outcome_unknown"
        | "invalid_packet_saved_record"
        | "invalid_packet_context_record"
        | "packet_context_inventory_limit"
        | "packet_context_snapshot_required" => StatusCode::SERVICE_UNAVAILABLE,
        "owner_authentication_required" => StatusCode::UNAUTHORIZED,
        "owner_peer_denied"
        | "owner_host_denied"
        | "owner_origin_denied"
        | "owner_client_required" => StatusCode::FORBIDDEN,
        "owner_approval_required"
        | "owner_approval_operation_mismatch"
        | "owner_approval_already_used" => StatusCode::FORBIDDEN,
        "owner_approval_unavailable" => StatusCode::SERVICE_UNAVAILABLE,
        "answer_reuse_disabled" | "generation_outcome_unknown" => StatusCode::SERVICE_UNAVAILABLE,
        "owner_api_tls_required" => StatusCode::UPGRADE_REQUIRED,
        "job_not_found"
        | "profile_not_found"
        | "agent_run_not_found"
        | "owner_route_not_found"
        | "resource_not_found"
        | "evidence_not_found" => StatusCode::NOT_FOUND,
        "saved_record_not_found" => StatusCode::NOT_FOUND,
        "job_shortlist_conflict" | "job_shortlist_write_conflict" => StatusCode::CONFLICT,
        "answer_draft_not_found"
        | "missing_input_not_found"
        | "private_resume_not_found"
        | "notification_not_found" => StatusCode::NOT_FOUND,
        "pdf_content_type_required" => StatusCode::UNSUPPORTED_MEDIA_TYPE,
        "resume_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "resume_encryption_unavailable"
        | "document_worker_unavailable"
        | "private_resume_outcome_unknown" => StatusCode::SERVICE_UNAVAILABLE,
        "invalid_resume_label"
        | "invalid_notification_id"
        | "invalid_notification_page"
        | "invalid_notification_record"
        | "invalid_resume_confirmation"
        | "invalid_pdf_upload"
        | "invalid_or_unsafe_pdf"
        | "invalid_pdf_extraction"
        | "pdf_validation_timeout"
        | "pdf_output_limit"
        | "pdf_memory_limit"
        | "pdf_memory_supervision_failed" => StatusCode::UNPROCESSABLE_ENTITY,
        "private_pdf_integrity_failed"
        | "private_pdf_checksum_failed"
        | "private_resume_changed"
        | "canonical_resume_changed"
        | "private_resume_binding_invalid"
        | "drive_resume_review_required"
        | "private_resume_insert_mismatch" => StatusCode::CONFLICT,
        "profile_method_not_allowed"
        | "match_method_not_allowed"
        | "saved_match_method_not_allowed"
        | "resource_read_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "missing_item_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "resource_list_method_not_allowed" | "evidence_patch_method_not_allowed" => {
            StatusCode::METHOD_NOT_ALLOWED
        }
        "profile_version_required" | "standard_link_version_required" => {
            StatusCode::PRECONDITION_REQUIRED
        }
        "standard_link_confirmation_required"
        | "resource_conflict"
        | "resource_insert_conflict" => StatusCode::CONFLICT,
        "answer_draft_stale" => StatusCode::CONFLICT,
        "generation_context_changed"
        | "answer_reuse_context_changed"
        | "answer_reuse_current_review_required" => StatusCode::CONFLICT,
        "missing_input_version_conflict"
        | "missing_input_packet_context_mismatch"
        | "missing_input_draft_context_mismatch"
        | "missing_input_identity_collision"
        | "factual_answer_and_evidence_note_required"
        | "sensitive_answer_not_retained"
        | "missing_input_context_changed_edit_before_approval" => StatusCode::CONFLICT,
        "profile_version_conflict" | "profile_changed_review_current_version" => {
            StatusCode::CONFLICT
        }
        "invalid_profile_confirmation"
        | "invalid_resource_selection"
        | "invalid_resource_record"
        | "invalid_resource_input"
        | "invalid_resource_page"
        | "invalid_answer_draft_record"
        | "invalid_answer_draft_review"
        | "invalid_missing_input_request"
        | "invalid_missing_input_record"
        | "invalid_answer_request"
        | "invalid_answer_reuse_approval"
        | "invalid_answer_reuse_record"
        | "answer_reuse_unsupported_intent"
        | "answer_reuse_job_required"
        | "answer_reuse_exact_job_required"
        | "answer_draft_context_mismatch"
        | "resource_inventory_limit"
        | "invalid_job_id"
        | "invalid_job_page"
        | "invalid_saved_job_record"
        | "invalid_match_result"
        | "profile_version_syntax"
        | "invalid_profile_input"
        | "profile_payload_limit"
        | "invalid_profile_record"
        | "invalid_profile_version"
        | "fictional_or_placeholder_profile_rejected" => StatusCode::UNPROCESSABLE_ENTITY,
        "agent_approval_not_pending"
        | "agent_approval_expired"
        | "agent_approval_context_changed"
        | "agent_replan_limit"
        | "agent_approval_limit"
        | "agent_revision_conflict"
        | "agent_control_revision_conflict"
        | "agent_request_key_conflict"
        | "agent_question_not_pending"
        | "owner_fact_not_confirmed"
        | "verified_profile_context_changed"
        | "verified_profile_identity_changed"
        | "agent_reconciliation_required"
        | "invalid_agent_control" => StatusCode::CONFLICT,
        "profile_database_error"
        | "agent_database_reconnecting"
        | "agent_database_unavailable"
        | "database_host_unavailable"
        | "verified_context_database_error"
        | "saved_jobs_database_error"
        | "application_history_database_error"
        | "owner_fact_database_error"
        | "agent_database_error"
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
