//! Read helpers for the existing owner-preference ledger; no implicit writes or DDL.
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
