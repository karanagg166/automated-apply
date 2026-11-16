//! Owner-reviewed local application history. No Gmail fetch, sending or provider-confirmation inference.
pub mod contract;
use crate::{Failure, Result};
use chrono::{DateTime, Duration, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
const PREFIX: &str = "gmail_application:";
pub const PATH: &str = "/api/v1/integrations/gmail/workspace/history";
#[derive(Clone, Copy)]
pub enum Route<'a> {
    List,
    Review,
    Forget(&'a str),
    Retention(&'a str),
}
impl Route<'_> {
    pub fn method(self) -> &'static str {
        match self {
            Self::List => "GET",
            Self::Retention(_) => "PUT",
            _ => "POST",
        }
    }
}
pub fn route(path: &str) -> Option<Route<'_>> {
    if path == PATH {
        return Some(Route::List);
    }
    let tail = path.strip_prefix(PATH)?.strip_prefix('/')?;
    if tail == "review" {
        return Some(Route::Review);
    }
    let (id, action) = tail.split_once('/')?;
    if !contract::identity(id) {
        return None;
    }
    match action {
        "forget" => Some(Route::Forget(id)),
        "retention" => Some(Route::Retention(id)),
        _ => None,
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("gmail_history_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_gmail_history_saved_record")
}
fn version(v: &Value) -> Result<i64> {
    v["version"]
        .as_i64()
        .filter(|n| *n >= 0)
        .ok_or_else(invalid)
}
fn next(v: &Value) -> Result<i64> {
    version(v)?.checked_add(1).ok_or_else(invalid)
}
fn stamp(at: DateTime<Utc>) -> String {
    at.to_rfc3339_opts(
        if at.timestamp_subsec_micros() == 0 {
            chrono::SecondsFormat::Secs
        } else {
            chrono::SecondsFormat::Micros
        },
        false,
    )
}
async fn put(tx: &mut Transaction<'_, Postgres>, key: &str, value: &Value) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(Failure("gmail_history_write_ack_failed"));
    }
    Ok(())
}
async fn get(tx: &mut Transaction<'_, Postgres>, id: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(format!("{PREFIX}{id}"))
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}
async fn list_in(tx: &mut Transaction<'_, Postgres>, now: DateTime<Utc>) -> Result<Vec<Value>> {
    let rows = crate::execution::reviewed_history::load_in(tx, now).await?;
    let mut ordered = Vec::with_capacity(rows.len());
    for value in rows {
        version(&value)?;
        let id = value["id"]
            .as_str()
            .filter(|s| contract::identity(s))
            .ok_or_else(invalid)?
            .to_owned();
        let date = contract::timestamp(&value["applied_at"]).ok_or_else(invalid)?;
        ordered.push((date, id, value));
    }
    ordered.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    Ok(ordered.into_iter().map(|(_, _, v)| v).collect())
}
fn duplicate(row: &Value, data: &Value, url: Option<&str>) -> bool {
    if let (Some(url), Some(old)) = (url, row["job_url"].as_str().filter(|s| !s.is_empty())) {
        url == old
    } else {
        row["company"].as_str().is_some_and(|v| {
            contract::folded(v) == contract::folded(data["company"].as_str().unwrap())
        }) && row["role"].as_str().is_some_and(|v| {
            contract::folded(v) == contract::folded(data["role"].as_str().unwrap())
        })
    }
}
async fn review_in(
    tx: &mut Transaction<'_, Postgres>,
    data: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let url = contract::canonical(data["job_url"].as_str());
    let identity = contract::opportunity(
        data["company"].as_str().ok_or_else(invalid)?,
        data["role"].as_str().ok_or_else(invalid)?,
        url.as_deref(),
    );
    let mut id = format!("{:x}", Sha256::digest(identity.as_bytes()))[..32].to_owned();
    let rows = list_in(tx, now).await?;
    let duplicates = rows
        .iter()
        .filter(|row| duplicate(row, data, url.as_deref()))
        .collect::<Vec<_>>();
    if duplicates.len() > 1 {
        return Err(Failure("gmail_history_identity_conflict"));
    }
    if let Some(row) = duplicates.first() {
        id = row["id"].as_str().ok_or_else(invalid)?.to_owned();
    }
    let old = get(tx, &id).await?.unwrap_or(json!({"version":0}));
    if version(&old)? != data["expected_version"].as_i64().ok_or_else(invalid)? {
        return Err(Failure("gmail_history_version_conflict"));
    }
    let old_active = old["deleted"] != true
        && contract::timestamp(&old["expires_at"]).is_some_and(|at| at > now);
    let mut evidence = if old_active {
        old.get("evidence")
            .and_then(Value::as_object)
            .cloned()
            .ok_or_else(invalid)?
    } else {
        serde_json::Map::new()
    };
    for (account, ids) in data["evidence"].as_object().ok_or_else(invalid)? {
        let mut merged = if let Some(old) = evidence.get(account) {
            old.as_array()
                .ok_or_else(invalid)?
                .iter()
                .map(|v| {
                    v.as_str()
                        .filter(|s| contract::identity(s))
                        .map(str::to_owned)
                        .ok_or_else(invalid)
                })
                .collect::<Result<std::collections::BTreeSet<_>>>()?
        } else {
            std::collections::BTreeSet::new()
        };
        for id in ids.as_array().ok_or_else(invalid)? {
            let id = id.as_str().ok_or_else(invalid)?;
            let saved:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('account_id',value->'account_id','expires_at',value->'expires_at') FROM owner_preferences WHERE key=$1 FOR SHARE").bind(format!("gmail_msg:{id}")).fetch_optional(&mut **tx).await.map_err(db)?;
            let saved = saved.ok_or(Failure("gmail_history_evidence_unavailable"))?;
            if saved["account_id"].as_str() != Some(account.as_str())
                || !contract::timestamp(&saved["expires_at"]).is_some_and(|at| at > now)
            {
                return Err(Failure("gmail_history_evidence_unavailable"));
            }
            merged.insert(id.to_owned());
        }
        evidence.insert(
            account.clone(),
            json!(merged.into_iter().take(100).collect::<Vec<_>>()),
        );
    }
    let mut value = data.clone();
    for key in ["expected_version", "owner_reviewed"] {
        value.as_object_mut().unwrap().remove(key);
    }
    value["id"] = json!(id);
    value["version"] = json!(next(&old)?);
    value["job_url"] = url
        .map(Value::String)
        .or_else(|| old_active.then(|| old["job_url"].clone()))
        .unwrap_or(Value::Null);
    value["evidence"] = Value::Object(evidence);
    value["confirmed_application"] = json!(
        data["confirmed_application"] == true || old_active && old["confirmed_application"] == true
    );
    value["status"] = if data["status"] == "uncertain" && old_active {
        old["status"].clone()
    } else {
        data["status"].clone()
    };
    value["reviewed_at"] = json!(stamp(now));
    value["expires_at"] = json!(stamp(
        now + Duration::days(data["retention_days"].as_i64().ok_or_else(invalid)?)
    ));
    put(tx, &format!("{PREFIX}{id}"), &value).await?;
    Ok(value)
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Result<Value> {
    if method != route.method() {
        return Err(Failure("gmail_history_method_not_allowed"));
    }
    if query.is_some() {
        return Err(Failure("invalid_gmail_history_contract"));
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        if matches!(route, Route::List) {
            sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                .execute(&mut *tx)
                .await
                .map_err(db)?;
        } else {
            sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                .execute(&mut *tx)
                .await
                .map_err(db)?;
            crate::execution::lock_owner_in(&mut tx).await?;
            sqlx::query("SELECT pg_advisory_xact_lock(407006,2)")
                .execute(&mut *tx)
                .await
                .map_err(db)?;
        }
        let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        if matches!(route, Route::List) {
            return Ok(json!({"history":list_in(&mut tx,now).await?}));
        }
        let kind = match route {
            Route::Review => contract::Kind::Review,
            Route::Forget(_) => contract::Kind::Version,
            Route::Retention(_) => contract::Kind::Retention,
            _ => unreachable!(),
        };
        let data = contract::normalize(
            kind,
            serde_json::from_slice(body).map_err(|_| Failure("invalid_gmail_history_contract"))?,
            now,
        )?;
        match route {
            Route::Review => review_in(&mut tx, &data, now).await,
            Route::Forget(id) | Route::Retention(id) => {
                let mut old = get(&mut tx, id)
                    .await?
                    .ok_or(Failure("gmail_history_version_conflict"))?;
                if old["version"] != data["expected_version"]
                    || matches!(route, Route::Retention(_)) && old["deleted"] == true
                {
                    return Err(Failure("gmail_history_version_conflict"));
                }
                let next = next(&old)?;
                if matches!(route, Route::Forget(_)) {
                    old = json!({"deleted":true,"version":next});
                    put(&mut tx, &format!("{PREFIX}{id}"), &old).await?;
                    Ok(json!({"deleted":true}))
                } else {
                    if !contract::timestamp(&old["expires_at"]).is_some_and(|at| at > now) {
                        return Err(Failure("gmail_history_expired_record"));
                    }
                    old["version"] = json!(next);
                    old["retention_days"] = data["retention_days"].clone();
                    old["expires_at"] = json!(stamp(
                        now + Duration::days(data["retention_days"].as_i64().ok_or_else(invalid)?)
                    ));
                    put(&mut tx, &format!("{PREFIX}{id}"), &old).await?;
                    Ok(old)
                }
            }
            Route::List => unreachable!(),
        }
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("gmail_history_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("gmail_history_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
/// Existing approved retention, bounded to100 metadata records per tick; no provider IO.
pub async fn maintenance(c: &mut PgConnection) -> Result<usize> {
    const CANDIDATES: &str = "SELECT key,value FROM owner_preferences WHERE (starts_with(key,'gmail_msg:') OR starts_with(key,'gmail_application:') OR starts_with(key,'gmail_draft_oauth:')) AND CASE WHEN pg_input_is_valid(value->>'expires_at','timestamp with time zone') THEN (value->>'expires_at')::timestamptz<=clock_timestamp() ELSE false END ORDER BY key LIMIT 100";
    let hint:Option<String>=sqlx::query_scalar("SELECT key FROM owner_preferences WHERE (starts_with(key,'gmail_msg:') OR starts_with(key,'gmail_application:') OR starts_with(key,'gmail_draft_oauth:')) AND CASE WHEN pg_input_is_valid(value->>'expires_at','timestamp with time zone') THEN (value->>'expires_at')::timestamptz<=clock_timestamp() ELSE false END LIMIT 1").fetch_optional(&mut *c).await.map_err(db)?;
    if hint.is_none() {
        return Ok(0);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        crate::execution::lock_owner_in(&mut tx).await?;
        sqlx::query("SELECT pg_advisory_xact_lock(407006,2)")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let rows: Vec<(String, Value)> = sqlx::query_as(CANDIDATES)
            .fetch_all(&mut *tx)
            .await
            .map_err(db)?;
        let count = rows.len();
        for (key, value) in rows {
            let scrubbed = if key.starts_with(PREFIX) {
                json!({"deleted":true,"version":next(&value)?})
            } else if key.starts_with("gmail_msg:") {
                json!({"status":"purged"})
            } else {
                json!({"consumed":true,"expired":true})
            };
            put(&mut tx, &key, &scrubbed).await?;
        }
        Ok(count)
    }
    .await;
    match result {
        Ok(count) => {
            tx.commit()
                .await
                .map_err(|_| Failure("gmail_history_commit_outcome_unknown"))?;
            Ok(count)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("gmail_history_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
