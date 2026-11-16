//! Native browser installations are owner-scoped bindings, never account identities.
//! Private host authentication does not authorize submissions or window creation.
use crate::{Failure, Result, configuration::boolean};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::{collections::BTreeMap, sync::LazyLock};
use subtle::ConstantTimeEq;
use uuid::Uuid;

pub mod commands;
mod form_questions;
mod form_receipts;
mod form_review;
pub mod form_service;
pub mod forms;
mod invalidation;
mod native;
mod status;
mod storage;
pub mod tasks;
use storage::*;

pub const NATIVE: &str = "/api/v1/local-agent/chrome";
pub const PROFILES: &str = "/api/v1/browser/chrome-profiles";
pub struct Settings {
    pub(crate) extension: Option<String>,
    pub(crate) native_enabled: bool,
    pub(crate) commands_enabled: bool,
    pub(crate) telegram_notices: bool,
    pub(crate) fixture_origin: Option<String>,
    pub(crate) fill_enabled: bool,
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let extension = values
            .get("CHROME_EXTENSION_ID")
            .filter(|s| !s.is_empty())
            .cloned();
        if extension
            .as_ref()
            .is_some_and(|s| s.len() != 32 || !s.bytes().all(|c| (b'a'..=b'p').contains(&c)))
        {
            return Err(Failure("invalid_browser_extension_id"));
        }
        let native_enabled = boolean(values, "CHROME_NATIVE_MESSAGING_ENABLED", false)?;
        if native_enabled && extension.is_none() {
            return Err(Failure("browser_extension_id_required"));
        }
        let fixture_origin = values
            .get("BROWSER_FIXTURE_ORIGIN")
            .filter(|s| !s.is_empty())
            .cloned();
        if let Some(origin) = fixture_origin.as_deref() {
            let fixture = values.get("ENVIRONMENT").is_some_and(|s| s == "testing")
                && boolean(values, "RUST_RUNTIME_FIXTURE", false)?;
            let u = reqwest::Url::parse(origin)
                .map_err(|_| Failure("invalid_browser_fixture_origin"))?;
            if !fixture
                || u.scheme() != "http"
                || u.host_str() != Some("127.0.0.1")
                || u.port().is_none()
                || u.origin().ascii_serialization() != origin
                || !u.username().is_empty()
                || u.password().is_some()
                || u.query().is_some()
                || u.fragment().is_some()
                || u.path() != "/"
            {
                return Err(Failure("invalid_browser_fixture_origin"));
            }
        }
        Ok(Self {
            extension,
            native_enabled,
            commands_enabled: boolean(values, "CHROME_PROFILE_COMMANDS_ENABLED", false)?,
            telegram_notices: crate::packet_notice::telegram_configured(values),
            fixture_origin,
            fill_enabled: boolean(values, "BROWSER_FILL_ENABLED", false)?,
        })
    }
    pub(crate) fn permits(&self, extension: Option<&str>) -> bool {
        self.native_enabled && extension.is_some() && self.extension.as_deref() == extension
    }
}
#[derive(Clone, Copy)]
pub enum Route {
    Native,
    List,
    Select,
    Disconnect(Uuid),
    Enqueue,
    Tasks,
    TaskApplication(Uuid),
    TaskControl(Uuid),
    Plans,
    PlanReview(Uuid),
}
impl Route {
    pub fn method(self) -> &'static str {
        if matches!(
            self,
            Self::List | Self::Tasks | Self::TaskApplication(_) | Self::Plans
        ) {
            "GET"
        } else {
            "POST"
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        NATIVE => Some(Route::Native),
        PROFILES => Some(Route::List),
        "/api/v1/browser/chrome-profiles/select" => Some(Route::Select),
        "/api/v1/browser/chrome-profiles/commands" => Some(Route::Enqueue),
        "/api/v1/browser/extension-tasks" => Some(Route::Tasks),
        "/api/v1/browser/plans" => Some(Route::Plans),
        _ if path.starts_with("/api/v1/browser/plans/") => path
            .strip_prefix("/api/v1/browser/plans/")
            .and_then(|s| s.strip_suffix("/review"))
            .and_then(|s| s.parse().ok())
            .map(Route::PlanReview),
        _ if path.starts_with("/api/v1/browser/extension-tasks/application/") => path
            .strip_prefix("/api/v1/browser/extension-tasks/application/")
            .and_then(|s| s.parse().ok())
            .map(Route::TaskApplication),
        _ if path.starts_with("/api/v1/browser/extension-tasks/") => path
            .strip_prefix("/api/v1/browser/extension-tasks/")
            .and_then(|s| s.strip_suffix("/control"))
            .and_then(|s| s.parse().ok())
            .map(Route::TaskControl),
        _ => path
            .strip_prefix("/api/v1/browser/chrome-profiles/")
            .and_then(|s| s.strip_suffix("/disconnect"))
            .and_then(|s| s.parse().ok())
            .map(Route::Disconnect),
    }
}
fn invalid() -> Failure {
    Failure("invalid_browser_profile_record")
}
fn request_error() -> Failure {
    Failure("invalid_browser_profile_request")
}
fn string<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().ok_or_else(invalid)
}
fn number(v: &Value, key: &str) -> Result<i64> {
    v[key].as_i64().filter(|n| *n >= 0).ok_or_else(invalid)
}
fn timestamp(value: &Value) -> Result<DateTime<Utc>> {
    value
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|t| t.with_timezone(&Utc))
        .ok_or_else(invalid)
}
fn terminal(value: &Value) -> bool {
    matches!(
        value["state"].as_str(),
        Some("completed" | "failed" | "expired" | "cancelled" | "outcome_unknown")
    )
}
fn task_terminal(value: &Value) -> bool {
    matches!(
        value["state"].as_str(),
        Some("FAILED_FINAL" | "SUBMISSION_UNKNOWN" | "SUBMITTED_CONFIRMED")
    )
}
pub fn online(value: &Value, now: DateTime<Utc>) -> Result<bool> {
    let connected = value["connected"].as_bool().ok_or_else(invalid)?;
    let window = value["window_id"].as_i64().is_some_and(|n| n >= 0);
    let elapsed = now.signed_duration_since(timestamp(&value["last_heartbeat"])?);
    // A future timestamp is not evidence of an indefinitely live installation.
    Ok(connected
        && window
        && elapsed.num_milliseconds() >= 0
        && elapsed.num_milliseconds() < 100_000)
}
pub fn public(value: &Value, selected: &Value, now: DateTime<Utc>) -> Result<Value> {
    let mut result = json!({});
    for key in [
        "id",
        "label",
        "version",
        "connected",
        "last_heartbeat",
        "browser_session_id",
        "window_id",
        "commands_enabled",
    ] {
        result[key] = value.get(key).cloned().ok_or_else(invalid)?;
    }
    for key in ["id", "browser_session_id"] {
        string(value, key)?.parse::<Uuid>().map_err(|_| invalid())?;
    }
    if number(value, "version")? < 1
        || value["commands_enabled"].as_bool().is_none()
        || value["label"].as_str().is_none()
    {
        return Err(invalid());
    }
    result["selected"] = json!(selected == &value["id"]);
    result["status"] = json!(if value["connected"] == false {
        "DISCONNECTED"
    } else if online(value, now)? {
        "CONNECTED"
    } else {
        "PROFILE_OFFLINE"
    });
    Ok(result)
}
fn body(bytes: &[u8]) -> Result<Value> {
    serde_json::from_slice(bytes).map_err(|_| request_error())
}
fn expected(value: &Value, minimum: i64) -> Result<i64> {
    crate::profile_contract::pagination_integer(value.clone(), minimum, i64::MAX)
        .map_err(|_| request_error())
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    bytes: &[u8],
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    forms: Option<form_service::Services<'_>>,
) -> Result<Value> {
    if method != route.method() {
        return Err(Failure("browser_profile_method_not_allowed"));
    }
    let input = if matches!(
        route,
        Route::List | Route::Tasks | Route::TaskApplication(_) | Route::Plans
    ) {
        Value::Null
    } else {
        body(bytes)?
    };
    let command = if matches!(route, Route::Native) {
        Some(native::Command::parse(input.clone())?)
    } else {
        None
    };
    let enqueue = if matches!(route, Route::Enqueue) {
        Some(commands::request(input.clone())?)
    } else {
        None
    };
    if !matches!(
        route,
        Route::Native
            | Route::List
            | Route::Enqueue
            | Route::Tasks
            | Route::TaskApplication(_)
            | Route::Plans
            | Route::PlanReview(_)
    ) {
        let keys = if matches!(route, Route::Select) {
            &["expected_version", "profile_binding_id"][..]
        } else if matches!(route, Route::TaskControl(_)) {
            &["expected_version", "action"][..]
        } else {
            &["expected_version"][..]
        };
        let object = input.as_object().ok_or_else(request_error)?;
        if object.keys().any(|k| !keys.contains(&k.as_str()))
            || !object.contains_key("expected_version")
            || (matches!(route, Route::Select) && !object.contains_key("profile_binding_id"))
        {
            return Err(request_error());
        }
        expected(
            &input["expected_version"],
            if matches!(route, Route::Select) { 0 } else { 1 },
        )?;
        if matches!(route, Route::Select) && !input["profile_binding_id"].is_null() {
            input["profile_binding_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(request_error)?;
        }
        if matches!(route, Route::TaskControl(_))
            && !matches!(
                input["action"].as_str(),
                Some("pause" | "resume" | "cancel")
            )
        {
            return Err(request_error());
        }
    }
    if matches!(route, Route::PlanReview(_))
        && (input
            .as_object()
            .is_none_or(|o| o.keys().any(|k| k != "field_ids"))
            || input["field_ids"]
                .as_array()
                .is_none_or(|a| a.len() > 24 || a.iter().any(|v| v.as_str().is_none())))
    {
        return Err(Failure("invalid_field_approval"));
    }
    if let Some(command) = command.as_ref()
        && command.name() == "get_application_task"
    {
        match tasks::read_without_owner(c, command, settings, packets).await {
            Ok(Some(value)) => return Ok(native::result(command, Ok(value))),
            Ok(None) => {}
            Err(e) if tasks::domain_denial(e) => return Ok(native::result(command, Err(e))),
            Err(e) => return Err(e),
        }
    }
    let mut tx = c.begin().await.map_err(db)?;
    if matches!(route, Route::PlanReview(_))
        || command.as_ref().is_some_and(|c| {
            matches!(
                c.name(),
                "inspect_form"
                    | "prepare_form_answers"
                    | "authorize_form"
                    | "record_form_fill"
                    | "ask_form_questions"
            ) || c.name() == "update_application_task"
                && c.value["task_event"] == "inspection_prepared"
        })
    {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
    }
    let result = async {
        match route {
            Route::Tasks => return tasks::listing(&mut tx).await,
            Route::TaskApplication(id) => return tasks::by_application(&mut tx, id).await,
            Route::Plans => return form_service::listing(&mut tx).await,
            _ => {}
        }
        if matches!(route, Route::List) {
            let read = status::snapshot(&mut tx, settings).await?;
            if read.offline.is_empty() && !read.expired {
                return Ok(read.data);
            }
        }
        // All lifecycle changes share the legacy owner row; no parallel writer family.
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        match route {
            Route::Native => {
                native::dispatch(
                    &mut tx,
                    command.as_ref().unwrap(),
                    settings,
                    packets,
                    forms,
                    now,
                )
                .await
            }
            Route::List => listing(&mut tx, settings, now).await,
            Route::Enqueue => {
                commands::enqueue(&mut tx, enqueue.as_ref().unwrap(), settings, packets, now).await
            }
            Route::Tasks | Route::TaskApplication(_) | Route::Plans => unreachable!(),
            Route::PlanReview(id) => {
                form_review::review(
                    &mut tx,
                    id,
                    &input["field_ids"],
                    settings,
                    packets,
                    forms.ok_or(Failure("browser_form_inspection_unavailable"))?,
                )
                .await
            }
            Route::TaskControl(id) => {
                let value = tasks::load(&mut tx, id).await?;
                tasks::control(
                    &mut tx,
                    value,
                    input["action"].as_str().unwrap(),
                    expected(&input["expected_version"], 1)?,
                    settings,
                    packets,
                    now,
                )
                .await
            }
            Route::Select => {
                select(
                    &mut tx,
                    expected(&input["expected_version"], 0)?,
                    input["profile_binding_id"]
                        .as_str()
                        .map(|s| s.parse::<Uuid>().unwrap()),
                    now,
                )
                .await
            }
            Route::Disconnect(id) => {
                disconnect(&mut tx, id, expected(&input["expected_version"], 1)?, now).await
            }
        }
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("browser_profile_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) if error == Failure("PROFILE_OFFLINE") => {
            // Offline enqueue can revoke old authority before denial, matching legacy behavior.
            tx.commit()
                .await
                .map_err(|_| Failure("browser_profile_commit_outcome_unknown"))?;
            Err(error)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
async fn select(
    tx: &mut Transaction<'_, Postgres>,
    version: i64,
    identity: Option<Uuid>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let current = selection(tx).await?;
    if current["version"] != version {
        return Err(Failure("PROFILE_SELECTION_CONFLICT"));
    }
    let identity = identity.map(|id| json!(id)).unwrap_or(Value::Null);
    if !identity.is_null() {
        if let Some(fixed) = get(tx, "chr_fixed_profile").await?
            && fixed["profile_binding_id"] != identity
        {
            return Err(Failure("FIXED_PROFILE_REQUIRED"));
        }
        let row = get(tx, &format!("chr_prof:{}", identity.as_str().unwrap()))
            .await?
            .ok_or(Failure("PROFILE_OFFLINE"))?;
        if row["connected"] != true {
            return Err(Failure("PROFILE_OFFLINE"));
        }
    }
    invalidation::invalidate(tx, &Value::Null, "profile_binding_required", now).await?;
    if !current["profile_binding_id"].is_null() {
        invalidation::invalidate(
            tx,
            &current["profile_binding_id"],
            "profile_selection_changed",
            now,
        )
        .await?;
    }
    let result = json!({"version":version.checked_add(1).ok_or_else(invalid)?,"profile_binding_id":identity});
    put(tx, "chr_selection", &result).await?;
    Ok(result)
}
async fn disconnect(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    version: i64,
    now: DateTime<Utc>,
) -> Result<Value> {
    let key = format!("chr_prof:{identity}");
    let mut row = get(tx, &key)
        .await?
        .ok_or(Failure("PROFILE_REVISION_CONFLICT"))?;
    if row["version"] != version {
        return Err(Failure("PROFILE_REVISION_CONFLICT"));
    }
    row["connected"] = json!(false);
    row["commands_enabled"] = json!(false);
    row["version"] = json!(version.checked_add(1).ok_or_else(invalid)?);
    put(tx, &key, &row).await?;
    invalidation::invalidate(tx, &json!(identity), "profile_disconnected", now).await?;
    let selected = selection(tx).await?;
    if selected["profile_binding_id"] == json!(identity) {
        select(tx, number(&selected, "version")?, None, now).await?;
    }
    Ok(json!({"disconnected":true,"submitted":false}))
}
async fn listing(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    _now: DateTime<Utc>,
) -> Result<Value> {
    // Re-read after acquiring the owner fence; a heartbeat may have made the initial read current.
    let read = status::snapshot(tx, settings).await?;
    for identity in &read.offline {
        invalidation::invalidate(tx, identity, "PROFILE_OFFLINE", read.now).await?;
    }
    if read.expired {
        invalidation::expire(tx, None, read.now).await?;
    }
    if read.offline.is_empty() && !read.expired {
        Ok(read.data)
    } else {
        Ok(status::snapshot(tx, settings).await?.data)
    }
}
