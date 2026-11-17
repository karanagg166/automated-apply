//! Existing owner preferences constrain capabilities independently of execution grants.
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;

pub(crate) const PATH: &str = "/api/v1/local-agent/policy";
const PLATFORMS: [&str; 9] = [
    "google_forms",
    "naukri",
    "wellfound",
    "instahyre",
    "work_at_a_startup",
    "internshala",
    "employer_forms",
    "gmail",
    "linkedin",
];
const PREFERENCES: [&str; 5] = [
    "approve",
    "automatic_preferred",
    "draft_only",
    "manual_only",
    "disabled",
];

fn default_for(platform: &str) -> &'static str {
    match platform {
        "naukri" => "automatic_preferred",
        "gmail" => "draft_only",
        "linkedin" => "manual_only",
        _ => "approve",
    }
}

fn initial() -> Value {
    let platforms: serde_json::Map<_, _> = PLATFORMS
        .into_iter()
        .map(|platform| (platform.to_owned(), json!(default_for(platform))))
        .collect();
    json!({"default":"approve","platforms":platforms})
}

fn known(value: &Value) -> Option<&'static str> {
    let value = value.as_str()?;
    PREFERENCES
        .into_iter()
        .find(|candidate| *candidate == value)
}

pub(crate) fn preference(saved: Option<&Value>, platform: &str) -> Result<&'static str> {
    let Some(saved) = saved else {
        return Ok(default_for(platform));
    };
    let platforms = saved["platforms"]
        .as_object()
        .ok_or(Failure("invalid_saved_platform_policy"))?;
    known(platforms.get(platform).unwrap_or(&saved["default"]))
        .ok_or(Failure("invalid_saved_platform_policy"))
}

fn db(_: sqlx::Error) -> Failure {
    Failure("platform_policy_database_error")
}

async fn load(connection: &mut PgConnection, lock: bool) -> Result<Option<(i32, Value)>> {
    let sql = if lock {
        "SELECT version, CASE WHEN octet_length(preferences::text) <= 8192 THEN preferences END
         FROM agent_policies WHERE key='primary' FOR UPDATE"
    } else {
        "SELECT version, CASE WHEN octet_length(preferences::text) <= 8192 THEN preferences END
         FROM agent_policies WHERE key='primary'"
    };
    let row: Option<(i32, Option<Value>)> = sqlx::query_as(sql)
        .fetch_optional(connection)
        .await
        .map_err(db)?;
    row.map(|(version, value)| {
        value
            .filter(|_| version >= 1)
            .map(|value| (version, value))
            .ok_or(Failure("invalid_saved_platform_policy"))
    })
    .transpose()
}

pub(crate) async fn saved(connection: &mut PgConnection) -> Result<Option<Value>> {
    Ok(load(connection, false).await?.map(|(_, value)| value))
}

pub(crate) async fn preference_in(
    connection: &mut PgConnection,
    platform: &str,
) -> Result<&'static str> {
    preference(saved(connection).await?.as_ref(), platform)
}

fn response(version: i32, preferences: &Value) -> Result<Value> {
    let platforms = preferences["platforms"]
        .as_object()
        .filter(|platforms| platforms.values().all(|value| known(value).is_some()))
        .ok_or(Failure("invalid_saved_platform_policy"))?;
    let default = known(&preferences["default"]).ok_or(Failure("invalid_saved_platform_policy"))?;
    Ok(json!({"version":version,"default":default,"platforms":platforms}))
}

fn request(body: &[u8]) -> Result<(i32, Value)> {
    let invalid = Failure("invalid_platform_policy");
    let body: Value = serde_json::from_slice(body).map_err(|_| invalid)?;
    let fields = body
        .as_object()
        .filter(|fields| {
            fields
                .keys()
                .all(|key| matches!(key.as_str(), "expected_version" | "default" | "platforms"))
        })
        .ok_or(invalid)?;
    let version = crate::profile_contract::pagination_integer(
        body["expected_version"].clone(),
        1,
        i64::from(i32::MAX),
    )
    .map_err(|_| invalid)? as i32;
    let default = fields
        .get("default")
        .map_or(Some("approve"), known)
        .ok_or(invalid)?;
    let platforms = body["platforms"]
        .as_object()
        .filter(|platforms| platforms.values().all(|value| known(value).is_some()))
        .ok_or(invalid)?;
    if platforms.len() != PLATFORMS.len()
        || PLATFORMS.iter().any(|key| !platforms.contains_key(*key))
    {
        return Err(Failure("invalid_policy_platforms"));
    }
    if !matches!(platforms["gmail"].as_str(), Some("draft_only" | "disabled"))
        || !matches!(
            platforms["linkedin"].as_str(),
            Some("manual_only" | "disabled")
        )
    {
        return Err(Failure("fixed_platform_policy"));
    }
    Ok((version, json!({"default":default,"platforms":platforms})))
}

pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    method: &str,
    body: &[u8],
) -> Result<Value> {
    match method {
        "GET" if body.is_empty() => {
            let (version, preferences) = load(connection, false)
                .await?
                .unwrap_or_else(|| (1, initial()));
            return response(version, &preferences);
        }
        "GET" => return Err(Failure("invalid_platform_policy")),
        "PUT" => {}
        _ => return Err(Failure("platform_policy_method_not_allowed")),
    }
    let (expected, preferences) = request(body)?;
    let version = expected
        .checked_add(1)
        .ok_or(Failure("policy_version_conflict"))?;
    let mut tx = connection.begin().await.map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let current = load(&mut tx, true).await?;
    if current.as_ref().map_or(1, |(version, _)| *version) != expected {
        tx.rollback().await.map_err(db)?;
        return Err(Failure("policy_version_conflict"));
    }
    let after: Option<(i32, Value)> = if current.is_some() {
        sqlx::query_as(
            "UPDATE agent_policies SET version=$1, preferences=$2 WHERE key='primary' AND version=$3
             RETURNING version,preferences",
        ).bind(version).bind(&preferences).bind(expected).fetch_optional(&mut *tx).await.map_err(db)?
    } else {
        sqlx::query_as(
            "INSERT INTO agent_policies(key,version,preferences) VALUES('primary',$1,$2)
             ON CONFLICT(key) DO NOTHING RETURNING version,preferences",
        )
        .bind(version)
        .bind(&preferences)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?
    };
    let target = (version, preferences);
    if after.as_ref() != Some(&target) {
        tx.rollback().await.map_err(db)?;
        return Err(Failure("platform_policy_write_ack_failed"));
    }
    let id = Uuid::new_v4();
    let event: Option<(Uuid, i32, Value)> = sqlx::query_as(
        "INSERT INTO agent_policy_events(id,version,preferences) VALUES($1,$2,$3)
         ON CONFLICT(version) DO NOTHING RETURNING id,version,preferences",
    )
    .bind(id)
    .bind(version)
    .bind(&target.1)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    let matches_event = |row: Option<(Uuid, i32, Value)>| {
        row.is_some_and(|(key, rev, prefs)| key == id && rev == version && prefs == target.1)
    };
    let saved_event =
        sqlx::query_as("SELECT id,version,preferences FROM agent_policy_events WHERE id=$1")
            .bind(id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    if !matches_event(event)
        || !matches_event(saved_event)
        || load(&mut tx, false).await?.as_ref() != Some(&target)
    {
        tx.rollback().await.map_err(db)?;
        return Err(Failure("platform_policy_write_ack_failed"));
    }
    tx.commit()
        .await
        .map_err(|_| Failure("platform_policy_outcome_unknown"))?;
    response(version, &target.1)
}
