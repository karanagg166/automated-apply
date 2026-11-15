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

mod invalidation;
mod native;
mod storage;
use storage::*;

pub const NATIVE: &str = "/api/v1/local-agent/chrome";
pub const PROFILES: &str = "/api/v1/browser/chrome-profiles";
pub struct Settings {
    pub(crate) extension: Option<String>,
    pub(crate) native_enabled: bool,
    pub(crate) commands_enabled: bool,
    pub(crate) telegram_notices: bool,
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
        Ok(Self {
            extension,
            native_enabled,
            commands_enabled: boolean(values, "CHROME_PROFILE_COMMANDS_ENABLED", false)?,
            telegram_notices: crate::packet_notice::telegram_configured(values),
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
}
impl Route {
    pub fn method(self) -> &'static str {
        if matches!(self, Self::List) {
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
) -> Result<Value> {
    if method != route.method() {
        return Err(Failure("browser_profile_method_not_allowed"));
    }
    let input = if matches!(route, Route::List) {
        Value::Null
    } else {
        body(bytes)?
    };
    let command = if matches!(route, Route::Native) {
        Some(native::Command::parse(input.clone())?)
    } else {
        None
    };
    if !matches!(route, Route::Native | Route::List) {
        let keys = if matches!(route, Route::Select) {
            &["expected_version", "profile_binding_id"][..]
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
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        // All lifecycle changes share the legacy owner row; no parallel writer family.
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        match route {
            Route::Native => {
                native::dispatch(&mut tx, command.as_ref().unwrap(), settings, now).await
            }
            Route::List => listing(&mut tx, settings, now).await,
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
    now: DateTime<Utc>,
) -> Result<Value> {
    let profiles = prefix(tx, "chr_prof:").await?;
    let selected = selection(tx).await?;
    for (_, profile) in &profiles {
        if !online(profile, now)? {
            invalidation::offline(tx, &profile["id"], now).await?;
        }
    }
    invalidation::expire(tx, None, now).await?;
    // Bounded SQL projections exclude credentials, raw form bodies and lease authority.
    let commands:Vec<Value>=sqlx::query_scalar("SELECT value-'lease_token'-'payload_hash' FROM (SELECT key,value,created_at FROM owner_preferences WHERE starts_with(key,'chr_cmd:') ORDER BY created_at DESC,key DESC LIMIT 30) s ORDER BY created_at,key").fetch_all(&mut **tx).await.map_err(db)?;
    let receipts:Vec<Value>=sqlx::query_scalar("SELECT value FROM (SELECT key,value,created_at FROM owner_preferences WHERE starts_with(key,'ext_receipt:') ORDER BY created_at DESC,key DESC LIMIT 30) s ORDER BY created_at,key").fetch_all(&mut **tx).await.map_err(db)?;
    let profiles = profiles
        .iter()
        .map(|(_, v)| public(v, &selected["profile_binding_id"], now))
        .collect::<Result<Vec<_>>>()?;
    Ok(
        json!({"selection":selected,"profiles":profiles,"commands":commands,"receipts":receipts,"channel_available":settings.commands_enabled}),
    )
}
