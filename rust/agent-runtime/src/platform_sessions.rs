//! Gesture observations and manual portal preferences. No account or API verification.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};

const PATH: &str = "/api/v1/local-agent/platforms";
struct Portal {
    code: &'static str,
    name: &'static str,
    login_url: &'static str,
}
static PORTALS: [Portal; 5] = [
    Portal {
        code: "naukri",
        name: "Naukri",
        login_url: "https://www.naukri.com/nlogin/login",
    },
    Portal {
        code: "wellfound",
        name: "Wellfound",
        login_url: "https://wellfound.com/login",
    },
    Portal {
        code: "instahyre",
        name: "Instahyre",
        login_url: "https://www.instahyre.com/login/",
    },
    Portal {
        code: "work_at_a_startup",
        name: "YC Work at a Startup",
        login_url: "https://account.ycombinator.com/magic?continue=https%3A%2F%2Fwww.workatastartup.com%2F",
    },
    Portal {
        code: "internshala",
        name: "Internshala",
        login_url: "https://internshala.com/login/",
    },
];

#[derive(Clone, Copy)]
pub(crate) enum Route<'a> {
    List,
    AcceptManual(&'a str),
    Forget(&'a str),
}
impl Route<'_> {
    pub(crate) fn method(self) -> &'static str {
        match self {
            Self::List => "GET",
            Self::AcceptManual(_) => "POST",
            Self::Forget(_) => "DELETE",
        }
    }
}

pub(crate) fn route(path: &str) -> Option<Route<'_>> {
    if path == PATH {
        return Some(Route::List);
    }
    let tail = path.strip_prefix(PATH)?.strip_prefix('/')?;
    match tail.split_once('/') {
        None if !tail.is_empty() => Some(Route::Forget(tail)),
        Some((code, "accept-manual")) if !code.is_empty() => Some(Route::AcceptManual(code)),
        _ => None,
    }
}

fn db(_: sqlx::Error) -> Failure {
    Failure("platform_session_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_saved_platform_session")
}
fn ack() -> Failure {
    Failure("platform_session_write_ack_failed")
}
fn portal(code: &str) -> Option<&'static Portal> {
    PORTALS.iter().find(|portal| portal.code == code)
}
fn state(value: &Value) -> Result<&str> {
    match value.get("state") {
        None => Ok("owner_action_required"),
        Some(value) => value
            .as_str()
            .filter(|s| {
                matches!(
                    *s,
                    "browser_session_observed" | "owner_action_required" | "manual_only"
                )
            })
            .ok_or_else(invalid),
    }
}
fn timestamp(value: &Value, key: &str) -> Result<Value> {
    if value[key].is_null() {
        return Ok(Value::Null);
    }
    let time = value[key]
        .as_str()
        .filter(|s| s.len() <= 40)
        .ok_or_else(invalid)?;
    DateTime::parse_from_rfc3339(time).map_err(|_| invalid())?;
    Ok(json!(time))
}
fn evidence(value: &Value) -> Result<&str> {
    match value.get("evidence_type") {
        None => Ok("none"),
        Some(value) => value
            .as_str()
            .filter(|s| {
                matches!(
                    *s,
                    "none" | "metadata_forgotten" | "extension_gesture_dom_indicator"
                )
            })
            .ok_or_else(invalid),
    }
}

pub(crate) async fn listing(connection: &mut PgConnection) -> Result<Vec<Value>> {
    let keys: Vec<_> = PORTALS
        .iter()
        .map(|portal| format!("portal_{}", portal.code))
        .collect();
    let saved: Vec<(String, Option<Value>)> = sqlx::query_as(
        "SELECT key, CASE WHEN octet_length(value::text) <= 8192 THEN value END
         FROM owner_preferences WHERE key=ANY($1)",
    )
    .bind(&keys)
    .fetch_all(connection)
    .await
    .map_err(db)?;
    PORTALS.iter().zip(keys).map(|(portal, key)| {
        let value = match saved.iter().find(|(saved_key, _)| saved_key == &key) {
            Some((_, Some(value))) if value.is_object() => value,
            Some(_) => return Err(invalid()),
            None => &Value::Null,
        };
        Ok(json!({"platform":portal.code,"name":portal.name,"login_url":portal.login_url,
            "state":state(value)?,"last_verification_time":timestamp(value,"last_verification_time")?,
            "evidence_type":evidence(value)?,"identity_verified":false,"api_connected":false,
            "capabilities":["manual_handoff","url_preview","gesture_session_observation"],
            "submission":"unsupported","owner_acceptance_required":value["manual_capability_accepted"] != true}))
    }).collect()
}

async fn saved(connection: &mut PgConnection, key: &str, lock: bool) -> Result<Option<Value>> {
    let sql = if lock {
        "SELECT CASE WHEN octet_length(value::text) <= 8192 THEN value END FROM owner_preferences WHERE key=$1 FOR UPDATE"
    } else {
        "SELECT CASE WHEN octet_length(value::text) <= 8192 THEN value END FROM owner_preferences WHERE key=$1"
    };
    let row: Option<Option<Value>> = sqlx::query_scalar(sql)
        .bind(key)
        .fetch_optional(connection)
        .await
        .map_err(db)?;
    row.map(|value| value.filter(Value::is_object).ok_or_else(invalid))
        .transpose()
}

fn observation(value: Option<&Value>, indicator: &str, now: DateTime<Utc>) -> Value {
    let forgotten = indicator == "forgotten";
    let accepted = !forgotten && value.is_some_and(|old| old["manual_capability_accepted"] == true);
    let state = if indicator == "signed_in_indicator" {
        "browser_session_observed"
    } else if accepted {
        "manual_only"
    } else {
        "owner_action_required"
    };
    json!({"state":state,"last_verification_time":(!forgotten).then(|| now.to_rfc3339()),
        "evidence_type":if forgotten {"metadata_forgotten"} else {"extension_gesture_dom_indicator"},
        "observation":indicator,"manual_capability_accepted":accepted})
}

pub(crate) fn observation_payload(value: &Value) -> Result<Value> {
    let platform = value["platform"]
        .as_str()
        .and_then(portal)
        .ok_or_else(invalid)?;
    let indicator = value["observation"]
        .as_str()
        .filter(|indicator| {
            matches!(
                *indicator,
                "signed_in_indicator" | "login_required" | "unverifiable"
            )
        })
        .ok_or_else(invalid)?;
    let time = timestamp(value, "last_verification_time")?;
    if value["identity_verified"] != false
        || value["api_connected"] != false
        || value["submitted"] != false
        || evidence(value)? != "extension_gesture_dom_indicator"
        || time.is_null()
        || !value["manual_capability_accepted"].is_boolean()
    {
        return Err(invalid());
    }
    Ok(
        json!({"platform":platform.code,"observation":indicator,"state":state(value)?,
        "last_verification_time":time,"manual_capability_accepted":value["manual_capability_accepted"],
        "evidence_type":"extension_gesture_dom_indicator","identity_verified":false,"api_connected":false,"submitted":false}),
    )
}

async fn save(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    old: Option<&Value>,
    value: &Value,
) -> Result<()> {
    let written: Option<Value> = if let Some(old) = old {
        sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value")
            .bind(key).bind(value).bind(old).fetch_optional(&mut **tx).await.map_err(db)?
    } else {
        sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING RETURNING value")
            .bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?
    };
    if written.as_ref() != Some(value) {
        return Err(ack());
    }
    verify_saved(tx, key, value).await
}

pub(crate) async fn verify_saved(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    value: &Value,
) -> Result<()> {
    if saved(tx, key, false).await?.as_ref() != Some(value) {
        return Err(ack());
    }
    Ok(())
}

pub(crate) async fn observe(
    tx: &mut Transaction<'_, Postgres>,
    url: Option<&str>,
    indicator: Option<&str>,
    now: DateTime<Utc>,
) -> Result<(String, Value, Value)> {
    let unsupported = Failure("unsupported_platform_observation");
    let url = url
        .and_then(crate::resources::public_https)
        .ok_or(unsupported)?;
    let platform = crate::browser_profiles::commands::page_kind(&url)?;
    let portal = portal(platform).ok_or(unsupported)?;
    let indicator = indicator
        .filter(|indicator| {
            matches!(
                *indicator,
                "signed_in_indicator" | "login_required" | "unverifiable"
            )
        })
        .ok_or(unsupported)?;
    let key = format!("portal_{}", portal.code);
    let old = saved(tx, &key, true).await?;
    let value = observation(old.as_ref(), indicator, now);
    save(tx, &key, old.as_ref(), &value).await?;
    let mut result = value.clone();
    result["platform"] = json!(platform);
    result["api_connected"] = json!(false);
    result["identity_verified"] = json!(false);
    result["submitted"] = json!(false);
    Ok((key, value, result))
}

pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    body: &[u8],
) -> Result<Value> {
    if method != route.method() {
        return Err(Failure("platform_session_method_not_allowed"));
    }
    if !body.is_empty() {
        return Err(Failure("invalid_platform_session_request"));
    }
    let code = match route {
        Route::List => return Ok(json!(listing(connection).await?)),
        Route::AcceptManual(code) | Route::Forget(code) => code,
    };
    let platform = portal(code).ok_or(Failure("unsupported_platform"))?;
    let mut tx = connection.begin().await.map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let key = format!("portal_{}", platform.code);
    let old = saved(&mut tx, &key, true).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let value = if matches!(route, Route::Forget(_)) {
        observation(old.as_ref(), "forgotten", now)
    } else {
        let mut value = old.clone().unwrap_or_else(|| json!({}));
        value["manual_capability_accepted"] = json!(true);
        value["manual_capability_accepted_at"] = json!(now.to_rfc3339());
        if state(&value)? != "browser_session_observed" {
            value["state"] = json!("manual_only");
        }
        value
    };
    timestamp(&value, "last_verification_time")?;
    timestamp(&value, "manual_capability_accepted_at")?;
    evidence(&value)?;
    if !value["observation"].is_null()
        && !matches!(
            value["observation"].as_str(),
            Some("signed_in_indicator" | "login_required" | "unverifiable" | "forgotten")
        )
    {
        return Err(invalid());
    }
    let response = Value::Object(
        value
            .as_object()
            .ok_or_else(invalid)?
            .iter()
            .filter(|(key, _)| {
                matches!(
                    key.as_str(),
                    "state"
                        | "last_verification_time"
                        | "observation"
                        | "evidence_type"
                        | "manual_capability_accepted"
                        | "manual_capability_accepted_at"
                )
            })
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect(),
    );
    if let Err(error) = save(&mut tx, &key, old.as_ref(), &value).await {
        tx.rollback().await.map_err(db)?;
        return Err(error);
    }
    tx.commit()
        .await
        .map_err(|_| Failure("platform_session_outcome_unknown"))?;
    Ok(response)
}
