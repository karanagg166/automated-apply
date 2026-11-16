//! Existing owner-preference ledger. Mutations require the shared owner lock; no DDL.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::{Postgres, Transaction};

pub(super) fn db(_: sqlx::Error) -> Failure {
    Failure("execution_database_error")
}
pub(super) fn invalid() -> Failure {
    Failure("invalid_execution_saved_record")
}
pub(super) fn revision(value: &Value) -> Result<i64> {
    value["revision"]
        .as_i64()
        .filter(|n| *n >= 0)
        .ok_or_else(invalid)
}
pub(super) async fn get(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}
pub(super) fn timestamp(value: &Value) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value.as_str().ok_or_else(invalid)?)
        .map(|d| d.with_timezone(&Utc))
        .map_err(|_| invalid())
}
pub(super) fn stamp(time: DateTime<Utc>) -> String {
    let micros = time.timestamp_subsec_micros();
    format!(
        "{}{}+00:00",
        time.format("%Y-%m-%dT%H:%M:%S"),
        if micros == 0 {
            String::new()
        } else {
            format!(".{micros:06}")
        }
    )
}
pub(super) fn next(value: &Value) -> Result<i64> {
    revision(value)?.checked_add(1).ok_or_else(invalid)
}
pub(super) async fn now(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    let value: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    timestamp(&value)
}
pub(super) async fn lock(tx: &mut Transaction<'_, Postgres>) -> Result<()> {
    let existing: Option<String> = sqlx::query_scalar(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if existing.is_none() {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('agent_conversation:primary','{}') ON CONFLICT(key) DO NOTHING").execute(&mut **tx).await.map_err(db)?;
        let found: Option<String> = sqlx::query_scalar(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
        if found.is_none() {
            return Err(Failure("execution_write_ack_failed"));
        }
    }
    Ok(())
}
pub(super) async fn put(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    value: &Value,
) -> Result<()> {
    let actual:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if actual.as_ref() != Some(value) {
        return Err(Failure("execution_write_ack_failed"));
    }
    Ok(())
}
